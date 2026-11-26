from datetime import datetime, timedelta, timezone, time

import httpx
import pytest

from services.geometry import Checkpoint
from services.weather import (
    MISSING,
    OK,
    OUT_OF_RANGE,
    WeatherError,
    fetch_checkpoint_weather,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
UNITS = {
    "time": "iso8601",
    "wind_speed_10m": "mp/h",
    "wind_gusts_10m": "mp/h",
    "rain": "inch",
    "showers": "inch",
    "snowfall": "inch",
}


def at(day, hour, minute=0, month=11):
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def cp(lat, lon, eta, index=0):
    return Checkpoint(index, 0.0, 0.0, lat, lon, eta)


def location(start, n, wind, gust, rain, showers, snow, units=None):
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)]
    return {
        "hourly_units": units or UNITS,
        "hourly": {
            "time": times,
            "wind_speed_10m": [wind(i) for i in range(n)],
            "wind_gusts_10m": [gust(i) for i in range(n)],
            "rain": [rain(i) for i in range(n)],
            "showers": [showers(i) for i in range(n)],
            "snowfall": [snow(i) for i in range(n)],
        },
    }


def make_client(
    status=200,
    wind=lambda i: 5.0,
    gust=lambda i: 10.0,
    rain=lambda i: 0.0,
    showers=lambda i: 0.0,
    snow=lambda i: 0.0,
    units=None,
):
    calls = []  # query params of every request

    def handler(request):
        p = request.url.params
        calls.append(dict(p))
        n_loc = len(p["latitude"].split(","))
        past, forecast = int(p["past_days"]), int(p["forecast_days"])
        start = datetime.combine(NOW.date() - timedelta(days=past), time(0), tzinfo=UTC)
        locs = [
            location(start, (past + forecast) * 24, wind, gust, rain, showers, snow, units)
            for _ in range(n_loc)
        ]
        return httpx.Response(status, json=locs if n_loc > 1 else locs[0])

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_wind_and_gusts_are_interpolated_linearly():
    client, _ = make_client(wind=lambda i: 5 * i, gust=lambda i: 10 * i)
    [w] = fetch_checkpoint_weather([cp(41.88, -87.63, at(25, 2, 30))], client, NOW)
    assert w.status == OK
    assert w.wind_mph == pytest.approx(12.5)
    assert w.gust_mph == pytest.approx(25)


@pytest.mark.parametrize(
    "hour, minute, label",
    [(2, 0, 3), (2, 30, 3), (2, 59, 3), (3, 0, 4)],
)
def test_rain_and_snow_use_the_hourly_bucket_containing_the_eta(hour, minute, label):
    # Values are totals for the preceding hour, so 02:00-02:59 reads the value labelled 03:00.
    client, _ = make_client(
        rain=lambda i: 0.01 * i, showers=lambda i: 0.1, snow=lambda i: 0.2 * i
    )
    [w] = fetch_checkpoint_weather([cp(41.88, -87.63, at(25, hour, minute))], client, NOW)
    assert w.rain_in_hr == pytest.approx(0.01 * label + 0.1)  # rain + showers
    assert w.snow_in_hr == pytest.approx(0.2 * label)


@pytest.mark.parametrize("eta", [at(20, 3, month=12), at(1, 3, month=6)])
def test_trip_entirely_outside_forecast_makes_no_request(eta):
    client, calls = make_client()
    result = fetch_checkpoint_weather([cp(41.88, -87.63, eta)], client, NOW)
    assert [w.status for w in result] == [OUT_OF_RANGE]
    assert calls == []


def test_partially_out_of_range_trip():
    client, calls = make_client()
    result = fetch_checkpoint_weather(
        [cp(41.88, -87.63, at(25, 14)), cp(41.88, -87.63, at(20, 3, month=12))], client, NOW
    )
    assert [w.status for w in result] == [OK, OUT_OF_RANGE]
    assert calls[0]["forecast_days"] == "16"  # clamped to the provider limit


@pytest.mark.parametrize(
    "etas, past_days, forecast_days",
    [
        ([at(25, 14), at(25, 23, 30)], "0", "2"),  # 23:30 needs the hour after it
        ([at(24, 20), at(25, 14)], "1", "1"),  # departure in the past
        ([at(25, 14), at(26, 3)], "0", "2"),
    ],
)
def test_forecast_window_covers_all_etas(etas, past_days, forecast_days):
    client, calls = make_client()
    result = fetch_checkpoint_weather([cp(41.88, -87.63, e) for e in etas], client, NOW)
    assert all(w.status == OK for w in result)
    assert calls[0]["past_days"] == past_days
    assert calls[0]["forecast_days"] == forecast_days


def test_duplicate_points_are_fetched_once_in_one_request():
    client, calls = make_client()
    cps = [
        cp(41.880, -87.630, at(25, 14)),
        cp(41.881, -87.629, at(25, 18)),  # same point after rounding, different ETA
        cp(43.04, -87.91, at(25, 16)),
    ]
    result = fetch_checkpoint_weather(cps, client, NOW)
    assert len(calls) == 1
    assert calls[0]["latitude"].count(",") == 1  # 2 unique locations
    assert [w.status for w in result] == [OK, OK, OK]


def test_single_location_response_is_an_object_not_a_list():
    client, _ = make_client()
    [w] = fetch_checkpoint_weather([cp(41.88, -87.63, at(25, 14))], client, NOW)
    assert w.status == OK


def test_many_locations_are_chunked():
    client, calls = make_client()
    cps = [cp(30 + i * 0.1, -90.0, at(25, 14), i) for i in range(120)]
    result = fetch_checkpoint_weather(cps, client, NOW)
    assert len(result) == 120
    assert [len(c["latitude"].split(",")) for c in calls] == [50, 50, 20]


def test_api_http_error():
    client, _ = make_client(status=500)
    with pytest.raises(WeatherError, match="request failed"):
        fetch_checkpoint_weather([cp(41.88, -87.63, at(25, 14))], client, NOW)


def test_api_timeout():
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(WeatherError):
        fetch_checkpoint_weather([cp(41.88, -87.63, at(25, 14))], client, NOW)


@pytest.mark.parametrize(
    "eta, status",
    [
        (at(25, 15, 30), MISSING),  # both neighbouring hours are null
        (at(25, 13, 30), OK),  # one neighbour is null: use the other
    ],
)
def test_missing_values(eta, status):
    client, _ = make_client(gust=lambda i: None if i >= 14 else 10.0)
    [w] = fetch_checkpoint_weather([cp(41.88, -87.63, eta)], client, NOW)
    assert w.status == status
    if status == OK:
        assert w.gust_mph == pytest.approx(10.0)


def test_unexpected_units_are_rejected():
    client, _ = make_client(units={**UNITS, "wind_gusts_10m": "km/h"})
    with pytest.raises(WeatherError, match="unit"):
        fetch_checkpoint_weather([cp(41.88, -87.63, at(25, 14))], client, NOW)


def test_wrong_number_of_locations_is_rejected():
    def handler(request):
        start = datetime(2026, 11, 25, tzinfo=UTC)
        loc = location(start, 24, lambda i: 5, lambda i: 10, lambda i: 0, lambda i: 0, lambda i: 0)
        return httpx.Response(200, json=[loc])  # one location, two requested

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cps = [cp(41.88, -87.63, at(25, 14)), cp(43.04, -87.91, at(25, 14))]
    with pytest.raises(WeatherError, match="unexpected number"):
        fetch_checkpoint_weather(cps, client, NOW)


def test_no_checkpoints_means_no_request():
    client, calls = make_client()
    assert fetch_checkpoint_weather([], client, NOW) == []
    assert calls == []


def test_request_asks_for_mph_inches_and_utc():
    client, calls = make_client()
    fetch_checkpoint_weather([cp(41.88, -87.63, at(25, 14))], client, NOW)
    params = calls[0]
    assert params["wind_speed_unit"] == "mph"
    assert params["precipitation_unit"] == "inch"
    assert params["timezone"] == "UTC"
    assert "wind_gusts_10m" in params["hourly"] and "snowfall" in params["hourly"]