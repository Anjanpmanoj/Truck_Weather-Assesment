from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from rest_framework.test import APIClient

from services.analysis import analyze_routes
from services.geometry import METERS_PER_MILE
from services.routing import LocationNotFound, NoRouteFound, Place, Route, RoutingError
from services.weather import MISSING, OK, CheckpointWeather, WeatherError

UTC = timezone.utc
URL = "/api/analyze"
LOAD = 25_000


def make_route(route_id, miles, hours, lat, points=11):
    step = miles / (points - 1)
    return Route(
        id=route_id,
        source="mapbox-alternative",
        coordinates=[[i * step / 69.0, lat] for i in range(points)],
        distances_m=[step * METERS_PER_MILE] * (points - 1),
        durations_s=[hours * 3600 / (points - 1)] * (points - 1),
        distance_mi=miles,
        duration_s=hours * 3600,
    )


def severe_at_50_on_route_1(checkpoints):
    out = []
    for c in checkpoints:
        gust = 50.0 if round(c.lat) == 1 and round(c.distance_mi) == 50 else 10.0
        out.append(CheckpointWeather(OK, gust * 0.6, gust, 0.0, 0.0))
    return out


def missing_at_50_on_route_1(checkpoints):
    out = []
    for c in checkpoints:
        if round(c.lat) == 1 and round(c.distance_mi) == 50:
            out.append(CheckpointWeather(MISSING))
        else:
            out.append(CheckpointWeather(OK, 6.0, 10.0, 0.0, 0.0))
    return out


def make_trip(n_routes=2, fetch=severe_at_50_on_route_1):
    routes = [make_route(f"route-{i}", 100, 2.0 + 0.5 * (i - 1), float(i)) for i in range(1, n_routes + 1)]
    result = analyze_routes(routes, datetime(2026, 11, 27, 15, tzinfo=UTC), LOAD, 25, fetch)
    return replace(
        result,
        notes=["only a note"],
        origin=Place("Chicago, Illinois", -87.6298, 41.8781),
        destination=Place("Milwaukee, Wisconsin", -87.9065, 43.0389),
    )


DEPARTURE = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)


def payload(drop=(), **overrides):
    body = {
        "origin": "Chicago, IL",
        "destination": "Milwaukee, WI",
        "departure_time": DEPARTURE.astimezone(timezone(timedelta(hours=-6))).isoformat(),
        "load_weight": LOAD,
        "interval_miles": 25,
    }
    body.update(overrides)
    for key in drop:
        del body[key]
    return body


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def no_service_calls(monkeypatch):
    def boom(**kwargs):
        raise AssertionError("analyze_trip must not be called for invalid input")

    monkeypatch.setattr("api.views.analyze_trip", boom)


@pytest.mark.parametrize("n_routes", [2, 3])
def test_success_response_shape(client, monkeypatch, n_routes):
    calls = []

    def fake_analyze_trip(**kwargs):
        calls.append(kwargs)
        return make_trip(n_routes)

    monkeypatch.setattr("api.views.analyze_trip", fake_analyze_trip)
    response = client.post(URL, payload(), format="json")
    assert response.status_code == 200
    body = response.json()

    # the validated, UTC-normalized request reached the service layer unchanged
    assert calls == [
        {
            "origin": "Chicago, IL",
            "destination": "Milwaukee, WI",
            "departure": DEPARTURE,
            "load_lb": float(LOAD),
            "interval_miles": 25,
        }
    ]
    assert body["origin"]["name"] == "Chicago, Illinois"
    assert body["destination"]["name"] == "Milwaukee, Wisconsin"
    assert body["request"] == {
        "departure_time": DEPARTURE.isoformat().replace("+00:00", "Z"),
        "load_weight": float(LOAD),
        "interval_miles": 25,
    }
    assert body["notes"] == ["only a note"]

    # exactly one route is flagged as recommended and it matches recommendation.route_id
    routes = body["routes"]
    assert [r["id"] for r in routes] == [f"route-{i}" for i in range(1, n_routes + 1)]
    assert [r["recommended"] for r in routes].count(True) == 1
    rec = body["recommendation"]
    assert rec["route_id"] == "route-2" and rec["safe"] is True
    assert next(r for r in routes if r["recommended"])["id"] == rec["route_id"]
    assert "Severe" in rec["explanation"] and rec["warnings"] == []

    route = routes[0]
    assert {"id", "label", "source", "recommended", "distance_mi", "duration_s", "arrival_time",
            "summary", "geometry", "segments", "checkpoints"} <= set(route)
    assert route["label"] == "Route 1"
    assert route["geometry"]["type"] == "LineString"
    assert len(route["geometry"]["coordinates"]) == 11
    assert set(route["summary"]["miles_by_level"]) == {
        "low", "moderate", "high", "severe", "no_travel", "unknown"}
    assert route["summary"]["miles_by_level"]["severe"] == 25.0
    assert route["summary"]["has_no_travel"] is False

    checkpoints = route["checkpoints"]
    assert [c["distance_mi"] for c in checkpoints] == [0, 25, 50, 75, 100]
    mid = checkpoints[2]
    assert mid["weather"] == {"status": "ok", "wind_mph": 30.0, "gust_mph": 50.0,
                              "rain_in_hr": 0.0, "snow_in_hr": 0.0}
    assert mid["risk"]["level"] == "severe" and mid["risk"]["value"] == 3
    assert "Wind gusts 50 mph" in mid["risk"]["rule"]
    assert mid["eta"].endswith("Z")

    # segments are contiguous, span the whole geometry and mirror checkpoint risk levels
    segs = route["segments"]
    assert segs[0]["start_index"] == 0 and segs[-1]["end_index"] == 10
    assert all(a["end_index"] == b["start_index"] for a, b in zip(segs, segs[1:]))
    assert [s["level"] for s in segs] == [c["risk"]["level"] for c in checkpoints]


def test_unknown_weather_is_reported_not_hidden(client, monkeypatch):
    monkeypatch.setattr("api.views.analyze_trip", lambda **kw: make_trip(2, missing_at_50_on_route_1))
    body = client.post(URL, payload(), format="json").json()
    route = body["routes"][0]
    mid = route["checkpoints"][2]
    assert mid["weather"] == {"status": "missing", "wind_mph": None, "gust_mph": None,
                              "rain_in_hr": None, "snow_in_hr": None}
    assert mid["risk"]["level"] == "unknown" and mid["risk"]["value"] is None
    assert route["summary"]["miles_by_level"]["unknown"] == 25.0
    assert body["recommendation"]["route_id"] == "route-2"


@pytest.mark.parametrize(
    "kwargs, field",
    [
        ({"drop": ["origin"]}, "origin"),
        ({"origin": "   "}, "origin"),
        ({"destination": "chicago, il"}, "destination"),  # same as origin
        ({"interval_miles": 30}, "interval_miles"),
        ({"interval_miles": "abc"}, "interval_miles"),
        ({"load_weight": -5}, "load_weight"),
        ({"load_weight": "heavy"}, "load_weight"),
        ({"load_weight": "nan"}, "load_weight"),
        ({"load_weight": 500_000}, "load_weight"),
        ({"departure_time": "2026-11-27T09:00:00"}, "departure_time"),  # no timezone
        ({"departure_time": "tomorrow morning"}, "departure_time"),
        ({"departure_time": (datetime.now(UTC) + timedelta(days=30)).isoformat()}, "departure_time"),
    ],
)
def test_invalid_input_returns_400(client, no_service_calls, kwargs, field):
    response = client.post(URL, payload(**kwargs), format="json")
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_input"
    assert field in error["details"]


@pytest.mark.parametrize(
    "exc, status, code",
    [
        (LocationNotFound("Could not find a US location for 'Xyzzy'"), 422, "location_not_found"),
        (NoRouteFound("No drivable route found between these locations"), 422, "no_route"),
        (RoutingError("Mapbox returned HTTP 401"), 502, "routing_unavailable"),
        (WeatherError("Weather service request failed: https://api.open-meteo.com/v1/forecast?x"),
         502, "weather_unavailable"),
        (RuntimeError("boom pk.secret-token"), 500, "internal_error"),
    ],
)
def test_service_failures_map_to_http_errors(client, monkeypatch, exc, status, code):
    def fail(**kwargs):
        raise exc

    monkeypatch.setattr("api.views.analyze_trip", fail)
    response = client.post(URL, payload(), format="json")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    if status >= 500:  # internals must not reach the client
        text = response.content.decode()
        assert not any(leak in text for leak in ("401", "https://", "pk.secret-token", "boom", "Traceback"))


def test_get_is_not_allowed(client):
    assert client.get(URL).status_code == 405