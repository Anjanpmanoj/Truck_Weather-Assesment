from datetime import datetime, timezone

import pytest

from services.corridor import MAX_SAMPLES, RoutePoint, forecast_corridor, sample_points
from services.weather import MISSING, OK, OUT_OF_RANGE, CheckpointWeather

REF = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)


def route_points(*distances):
    return [RoutePoint(40.0 + d / 100, -90.0, float(d)) for d in distances]


def ok(gust=10.0, rain=0.0, snow=0.0):
    return CheckpointWeather(OK, gust * 0.6, gust, rain, snow)


def fetcher(make, calls=None):
    """Fake hourly forecast: make(point_index, hour) -> CheckpointWeather."""

    def fetch(points, start, hours):
        if calls is not None:
            calls.append(len(points))
        assert start == REF and hours == 48
        return [[make(i, h) for h in range(hours + 1)] for i in range(len(points))]

    return fetch


def test_sample_points_keeps_ends_and_thins_to_spacing():
    sampled = sample_points(route_points(*range(0, 101, 10)))
    assert [p.distance_mi for p in sampled] == [0, 30, 60, 90, 100]


def test_sample_points_never_exceed_the_cap():
    points = route_points(*range(0, 4001, 10))
    sampled = sample_points(points)
    assert len(sampled) <= MAX_SAMPLES
    assert sampled[0] == points[0] and sampled[-1] == points[-1]


def test_sample_points_two_points_unchanged():
    points = route_points(0, 50)
    assert sample_points(points) == points


def test_hourly_risk_and_values_for_every_hour():
    result = forecast_corridor(
        route_points(0, 50), 10_000, REF, fetcher(lambda i, h: ok(gust=[10, 30, 40, 50, 60][min(h // 12, 4)]))
    )
    assert result.hours == 48 and result.reference_time == REF
    expected = [0] * 12 + [1] * 12 + [2] * 12 + [3] * 12 + [4]  # Low .. No Travel
    for point in result.points:
        assert point.risk == expected
        assert len(point.gust_mph) == 49
        assert point.gust_mph[0] == 10 and point.gust_mph[48] == 60
    assert result.unknown_cells == 0 and result.total_cells == 2 * 49


@pytest.mark.parametrize("load, expected", [(40_000, 2), (41_000, 3)])
def test_load_rules_apply_to_hourly_wind(load, expected):
    result = forecast_corridor(route_points(0, 50), load, REF, fetcher(lambda i, h: ok(gust=40)))
    assert result.points[0].risk == [expected] * 49  # 40 mph gusts: High, or Severe above 40,000 lb


def test_rain_and_snow_raise_hourly_risk():
    def make(i, h):
        if h == 5:
            return ok(rain=0.6)
        if h == 7:
            return ok(snow=3.5)
        return ok()

    risk = forecast_corridor(route_points(0, 50), 10_000, REF, fetcher(make)).points[0].risk
    assert (risk[4], risk[5], risk[6], risk[7]) == (0, 3, 0, 4)


def test_missing_forecast_is_unknown_not_low():
    def make(i, h):
        if i == 0 and h == 3:
            return CheckpointWeather(MISSING)
        if h >= 40:
            return CheckpointWeather(OUT_OF_RANGE)
        return ok()

    result = forecast_corridor(route_points(0, 50), 10_000, REF, fetcher(make))
    first = result.points[0]
    assert first.risk[3] is None and first.gust_mph[3] is None
    assert first.risk[2] == 0
    assert all(r is None for r in first.risk[40:])
    assert result.unknown_cells == 1 + 9 + 9 and result.total_cells == 98


def test_fetches_once_with_a_bounded_number_of_samples():
    calls = []
    result = forecast_corridor(
        route_points(*range(0, 4001, 10)), 10_000, REF, fetcher(lambda i, h: ok(), calls)
    )
    assert len(calls) == 1 and calls[0] <= MAX_SAMPLES
    assert len(result.points) == calls[0]