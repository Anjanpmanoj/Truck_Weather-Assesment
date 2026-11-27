from datetime import datetime, timedelta, timezone

import pytest
from rest_framework.test import APIClient

from services.weather import MISSING, OK, CheckpointWeather, WeatherError

UTC = timezone.utc
URL = "/api/forecast-corridor"
POINTS = [{"lat": 41.0 + i * 0.3, "lon": -87.6, "distance_mi": i * 25.0} for i in range(5)]


def payload(drop=(), **overrides):
    body = {"points": POINTS, "load_weight": 25_000}
    body.update(overrides)
    for key in drop:
        del body[key]
    return body


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def forecast_calls(monkeypatch):
    calls = []

    def fetch(points, start, hours):
        calls.append({"points": list(points), "start": start, "hours": hours})
        return [
            [CheckpointWeather(OK, 6.0, 40.0 if h >= 24 else 10.0, 0.0, 0.0) for h in range(hours + 1)]
            for _ in points
        ]

    monkeypatch.setattr("services.corridor.fetch_hourly_forecast", fetch)
    return calls


def test_success_response_shape(client, forecast_calls):
    response = client.post(URL, payload(), format="json")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"reference_time", "hours", "points", "warnings"}
    assert body["hours"] == 48 and body["warnings"] == []
    assert body["reference_time"].endswith(":00:00Z")  # floored to the hour
    assert forecast_calls[0]["start"].minute == 0 and forecast_calls[0]["hours"] == 48
    assert len(forecast_calls) == 1  # one forecast fetch, not one per hour

    assert len(body["points"]) == 5
    point = body["points"][4]
    assert set(point) == {"lat", "lon", "distance_mi", "risk", "gust_mph", "rain_in_hr", "snow_in_hr"}
    assert point["distance_mi"] == 100.0
    assert all(len(point[k]) == 49 for k in ("risk", "gust_mph", "rain_in_hr", "snow_in_hr"))
    assert point["risk"][0] == 0 and point["risk"][24] == 2  # gusts 10 mph, then 40 mph (High)
    assert point["gust_mph"][30] == 40.0


def test_explicit_reference_time_is_floored_to_the_hour(client, forecast_calls):
    reference = (datetime.now(UTC) + timedelta(days=1)).replace(minute=37, second=12, microsecond=0)
    response = client.post(URL, payload(reference_time=reference.isoformat()), format="json")
    assert response.status_code == 200
    assert forecast_calls[0]["start"] == reference.replace(minute=0, second=0)


def test_missing_forecast_is_null_and_warned(client, monkeypatch):
    def fetch(points, start, hours):
        return [
            [CheckpointWeather(OK, 6.0, 10.0, 0.0, 0.0) if h < 40 else CheckpointWeather(MISSING)
             for h in range(hours + 1)]
            for _ in points
        ]

    monkeypatch.setattr("services.corridor.fetch_hourly_forecast", fetch)
    body = client.post(URL, payload(), format="json").json()
    point = body["points"][0]
    assert point["risk"][39] == 0 and point["risk"][40] is None
    assert point["gust_mph"][40] is None
    assert any("Unknown" in w for w in body["warnings"])


@pytest.mark.parametrize(
    "kwargs, field",
    [
        ({"drop": ["points"]}, "points"),
        ({"points": POINTS[:1]}, "points"),
        ({"points": [{"lat": 41.0, "lon": -87.6, "distance_mi": float(i)} for i in range(401)]}, "points"),
        ({"points": [{**POINTS[0], "lat": 95}, *POINTS[1:]]}, "points"),
        ({"points": list(reversed(POINTS))}, "points"),
        ({"points": [{**p, "distance_mi": 10.0} for p in POINTS]}, "points"),
        ({"load_weight": -1}, "load_weight"),
        ({"load_weight": "nan"}, "load_weight"),
        ({"reference_time": "2026-11-27T09:00:00"}, "reference_time"),
        ({"reference_time": (datetime.now(UTC) + timedelta(days=20)).isoformat()}, "reference_time"),
        ({"reference_time": (datetime.now(UTC) - timedelta(days=3)).isoformat()}, "reference_time"),
    ],
)
def test_invalid_input_returns_400(client, forecast_calls, kwargs, field):
    response = client.post(URL, payload(**kwargs), format="json")
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_input" and field in error["details"]
    assert forecast_calls == []  # nothing was fetched for invalid input


def test_weather_failure_returns_502_without_internals(client, monkeypatch):
    def fail(points, start, hours):
        raise WeatherError("Weather service request failed: https://api.open-meteo.com/v1/forecast?x")

    monkeypatch.setattr("services.corridor.fetch_hourly_forecast", fail)
    response = client.post(URL, payload(), format="json")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "weather_unavailable"
    assert "https://" not in response.content.decode()