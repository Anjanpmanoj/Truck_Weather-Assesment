from datetime import datetime, timezone

import pytest

from services.weather import OK, OUT_OF_RANGE, fetch_hourly_forecast
from tests.test_weather import NOW, make_client

POINTS = [(41.88, -87.63), (43.04, -87.91)]


def test_all_hours_come_from_one_batched_request():
    client, calls = make_client()
    result = fetch_hourly_forecast(POINTS, NOW, client=client, now=NOW)
    assert len(calls) == 1  # not one per hour or per point
    assert calls[0]["latitude"].count(",") == 1  # both locations together
    assert calls[0]["past_days"] == "0" and calls[0]["forecast_days"] == "3"
    assert len(result) == 2 and all(len(hours) == 49 for hours in result)
    assert all(w.status == OK for hours in result for w in hours)


def test_hourly_values_follow_the_clock():
    # The fake series starts at 00:00 on day 1: value i is the hour index.
    client, _ = make_client(gust=lambda i: float(i), rain=lambda i: 0.01 * i)
    hours = fetch_hourly_forecast(POINTS[:1], NOW, client=client, now=NOW)[0]  # NOW is 12:00
    assert [w.gust_mph for w in hours] == pytest.approx([12.0 + h for h in range(49)])
    assert hours[0].rain_in_hr == pytest.approx(0.13)  # bucket labelled 13:00 covers 12:00-13:00
    assert hours[10].rain_in_hr == pytest.approx(0.23)


def test_duplicate_points_are_fetched_once():
    client, calls = make_client()
    result = fetch_hourly_forecast([(41.880, -87.630), (41.881, -87.629)], NOW, client=client, now=NOW)
    assert calls[0]["latitude"].count(",") == 0  # one location
    assert result[0] == result[1]


@pytest.mark.parametrize("start", [datetime(2026, 12, 20, 12, tzinfo=timezone.utc)])
def test_period_beyond_the_forecast_makes_no_request(start):
    client, calls = make_client()
    result = fetch_hourly_forecast(POINTS, start, client=client, now=NOW)
    assert calls == []
    assert all(w.status == OUT_OF_RANGE for hours in result for w in hours)


def test_hours_past_the_end_of_the_forecast_are_out_of_range():
    client, calls = make_client()
    start = datetime(2026, 12, 9, 12, tzinfo=timezone.utc)  # forecast ends 2026-12-10 23:00
    hours = fetch_hourly_forecast(POINTS[:1], start, client=client, now=NOW)[0]
    assert calls[0]["forecast_days"] == "16"
    assert hours[35].status == OK and hours[36].status == OUT_OF_RANGE


def test_no_points_means_no_request():
    client, calls = make_client()
    assert fetch_hourly_forecast([], NOW, client=client, now=NOW) == []
    assert calls == []