from datetime import datetime, timedelta, timezone

import pytest

from services import analysis
from services.analysis import analyze_routes, analyze_trip, represented_miles
from services.geometry import METERS_PER_MILE
from services.risk import RiskLevel
from services.routing import Place, Route, RoutesResult
from services.weather import MISSING, OK, OUT_OF_RANGE, CheckpointWeather

DEPART = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
L, M, H, S, N = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)


def route(route_id, miles, hours, lat):
    """A one-segment route; `lat` lets the fake weather tell routes apart."""
    return Route(
        id=route_id,
        source="mapbox-alternative",
        coordinates=[[0.0, lat], [miles / 69.0, lat]],
        distances_m=[miles * METERS_PER_MILE],
        durations_s=[hours * 3600.0],
        distance_mi=miles,
        duration_s=hours * 3600.0,
    )


def wx(gust=10.0, rain=0.0, snow=0.0):
    return CheckpointWeather(OK, gust * 0.6, gust, rain, snow)


def fetcher(scenario):
    """Fake weather: scenario(route_lat, distance_mi) -> CheckpointWeather."""
    calls = []

    def fetch(checkpoints):
        calls.append(len(checkpoints))
        return [scenario(c.lat, c.distance_mi) for c in checkpoints]

    fetch.calls = calls
    return fetch


def gusts(spec):
    """spec: {route_number: gust or callable(distance_mi) -> gust}"""

    def scenario(lat, dist):
        g = spec[round(lat)]
        return wx(g(dist) if callable(g) else g)

    return scenario


def run(routes, scenario, load=10_000, interval=25):
    return analyze_routes(routes, DEPART, load, interval, fetcher(scenario))


R1 = lambda: route("route-1", 100, 2.0, 1.0)  # fastest
R2 = lambda: route("route-2", 100, 2.5, 2.0)
R3 = lambda: route("route-3", 100, 3.0, 3.0)


@pytest.mark.parametrize(
    "distances, expected",
    [([0, 25, 50, 75, 92], [12.5, 25, 25, 21, 8.5]), ([0, 100], [50, 50])],
)
def test_represented_miles_sum_to_route_length(distances, expected):
    got = represented_miles(distances)
    assert got == pytest.approx(expected)
    assert sum(got) == pytest.approx(distances[-1])


def test_distance_weighted_miles_and_average_risk():
    by_distance = {0: 10, 25: 30, 50: 40, 75: 50, 100: 60}  # Low .. No Travel
    result = run([R1()], gusts({1: lambda d: by_distance[round(d)]}))
    a = result.routes[0]
    assert a.miles_by_level == pytest.approx({L: 12.5, M: 25, H: 25, S: 25, N: 12.5})
    assert a.unknown_mi == 0
    assert a.avg_risk == pytest.approx(2.0)  # (25*1 + 25*2 + 25*3 + 12.5*4) / 100
    assert a.has_no_travel
    assert a.arrival == DEPART + timedelta(hours=2)


@pytest.mark.parametrize("load, expected", [(40_000, H), (41_000, S)])
def test_load_weight_changes_the_risk_level(load, expected):
    a = run([R1()], gusts({1: 40}), load=load).routes[0]
    assert a.miles_by_level[expected] == pytest.approx(100)


def test_missing_weather_is_not_treated_as_safe():
    def scenario(lat, dist):
        if round(dist) == 50:
            return CheckpointWeather(MISSING)
        if round(dist) == 75:
            return CheckpointWeather(OUT_OF_RANGE)
        return wx(10)

    a = run([R1()], scenario).routes[0]
    assert a.unknown_mi == pytest.approx(50)
    assert a.miles_by_level[L] == pytest.approx(50)  # unknown is not added to Low
    assert a.avg_risk == pytest.approx(1.0)  # unknown counted as High: 50 * 2 / 100
    unknown = [c for c in a.checkpoints if c.level is None]
    assert len(unknown) == 2
    assert all("not as safe" in c.rule for c in unknown)


def test_weather_is_fetched_once_for_all_routes():
    fetch = fetcher(gusts({1: 10, 2: 10, 3: 10}))
    analyze_routes([R1(), R2(), R3()], DEPART, 10_000, 25, fetch)
    assert fetch.calls == [15]  # 3 routes x 5 checkpoints in a single call


def test_fewest_severe_miles_beats_a_faster_route():
    spec = {1: lambda d: 50 if round(d) in (25, 50) else 10, 2: 10}
    result = run([R1(), R2()], gusts(spec))
    rec = result.recommendation
    assert rec.route_id == "route-2" and rec.safe
    assert result.routes[0].miles_by_level[S] == pytest.approx(50)
    assert "0 Severe miles versus 50" in rec.explanation
    assert "30 min longer" in rec.explanation


def test_fewer_high_miles_when_severe_is_tied():
    spec = {1: lambda d: 40 if round(d) in (25, 50) else 10, 2: lambda d: 40 if round(d) == 25 else 10}
    rec = run([R1(), R2()], gusts(spec)).recommendation
    assert rec.route_id == "route-2"
    assert "25 High-risk miles versus 50" in rec.explanation


def test_lower_average_risk_when_severe_and_high_are_tied():
    spec = {1: lambda d: 30 if round(d) in (25, 50, 75) else 10, 2: lambda d: 30 if round(d) == 50 else 10}
    rec = run([R1(), R2()], gusts(spec)).recommendation
    assert rec.route_id == "route-2"
    assert "lower average risk" in rec.explanation


def test_shortest_time_when_risk_is_equal():
    routes = [route("route-1", 100, 2.0, 1.0), route("route-2", 100, 1.8, 2.0)]
    rec = run(routes, gusts({1: 10, 2: 10})).recommendation
    assert rec.route_id == "route-2"
    assert "similar" in rec.explanation


def test_no_travel_route_loses_even_when_the_other_has_severe_miles():
    spec = {1: lambda d: 60 if round(d) == 75 else 10, 2: lambda d: 50 if round(d) in (25, 50, 75) else 10}
    result = run([R1(), R2()], gusts(spec))
    assert result.routes[0].miles_by_level[S] == 0  # route 1 would win on Severe miles alone
    assert result.recommendation.route_id == "route-2"
    assert result.recommendation.safe
    assert "avoids No Travel" in result.recommendation.explanation


def test_all_routes_with_no_travel_warns_and_is_not_safe():
    spec = {
        1: lambda d: 60 if round(d) == 50 else 10,
        2: lambda d: 60 if round(d) in (25, 50) else 10,
    }
    rec = run([R1(), R2()], gusts(spec)).recommendation
    assert rec.route_id == "route-1"  # least No Travel miles
    assert not rec.safe
    assert "No route is safe" in rec.explanation
    assert any("different time" in w for w in rec.warnings)


def test_unknown_weather_loses_to_a_known_clean_route():
    def scenario(lat, dist):
        return CheckpointWeather(MISSING) if round(lat) == 1 else wx(10)

    rec = run([R1(), R2()], scenario).recommendation  # route 1 is faster but unknown
    assert rec.route_id == "route-2"
    assert rec.warnings == []


def test_recommended_route_with_unknown_miles_gets_a_warning():
    def scenario(lat, dist):
        if round(lat) == 1:
            return CheckpointWeather(MISSING) if round(dist) in (50, 75) else wx(10)
        return wx(50 if round(dist) == 25 else 10)  # route 2: 25 Severe miles

    rec = run([R1(), R2()], scenario).recommendation
    assert rec.route_id == "route-1"  # unknown ranks as High, which is below Severe
    assert any("no forecast data" in w for w in rec.warnings)


def test_no_forecast_at_all_falls_back_to_travel_time():
    routes = [route("route-1", 100, 2.0, 1.0), route("route-2", 100, 1.8, 2.0)]
    rec = run(routes, lambda lat, dist: CheckpointWeather(OUT_OF_RANGE)).recommendation
    assert rec.route_id == "route-2"
    assert "No forecast is available" in rec.explanation
    assert any("treated as High risk" in w for w in rec.warnings)


def test_sub_mile_differences_are_ties():
    # Route 1 has only 0.2 mi of Severe, at the destination: it must not outweigh time.
    routes = [route("route-1", 100.4, 2.0, 1.0), route("route-2", 100, 2.5, 2.0)]
    spec = {1: lambda d: 50 if d > 100 else 10, 2: 10}
    result = run(routes, gusts(spec))
    assert result.routes[0].miles_by_level[S] == pytest.approx(0.2)
    assert result.recommendation.route_id == "route-1"


def test_single_route_is_explained():
    rec = run([R1()], gusts({1: 10})).recommendation
    assert rec.route_id == "route-1"
    assert "only available route" in rec.explanation


def test_analyze_trip_combines_routing_and_weather(monkeypatch):
    found = RoutesResult(Place("Origin", 0.0, 0.0), Place("Dest", 1.0, 1.0), [R1(), R2()], ["only 2 routes"])
    monkeypatch.setattr(analysis, "find_routes", lambda origin, destination: found)
    monkeypatch.setattr(analysis, "fetch_checkpoint_weather", fetcher(gusts({1: 10, 2: 10})))
    result = analyze_trip("Origin", "Dest", DEPART, 10_000, 25)
    assert result.origin.name == "Origin" and result.destination.name == "Dest"
    assert result.notes == ["only 2 routes"]
    assert len(result.routes) == 2
    assert result.recommendation.route_id == "route-1"