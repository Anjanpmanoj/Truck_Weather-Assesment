import math
from urllib.parse import unquote

import httpx
import pytest

from services.geometry import METERS_PER_MILE, generate_checkpoints
from services.routing import Place, RoutingError, find_routes, geocode
from datetime import datetime, timezone

O, D = (-90.0, 40.0), (-90.0, 42.0)  # a ~138 mile north-south trip
PLACES = {"Origin, US": O, "Dest, US": D}
DEPART = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def mapbox_token(monkeypatch):
    monkeypatch.setenv("MAPBOX_TOKEN", "pk.test-token")


def _dist_m(a, b):
    dx = (b[0] - a[0]) * math.cos(math.radians((a[1] + b[1]) / 2)) * 111_320
    dy = (b[1] - a[1]) * 110_574
    return math.hypot(dx, dy)


def fake_route(points, speed=25.0, per_leg=30):
    """A Mapbox-shaped route through `points` with per-segment annotations."""
    coords = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        for k in range(per_leg):
            t = k / per_leg
            coords.append([x0 + t * (x1 - x0), y0 + t * (y1 - y0)])
    coords.append(list(points[-1]))
    dists = [_dist_m(a, b) for a, b in zip(coords, coords[1:])]
    durs = [d / speed for d in dists]
    return {
        "geometry": {"coordinates": coords},
        "distance": sum(dists),
        "duration": sum(durs),
        "legs": [{"annotation": {"distance": dists, "duration": durs}}],
    }


A = fake_route([O, D])  # straight and fastest
B = fake_route([O, (-89.9, 41.0), D], speed=24)  # alternative bulging east
W = fake_route([O, (-90.4, 41.0), D])  # a real detour via a western waypoint


def make_client(primary, waypoint_routes=(), directions_status=200, waypoint_status=200):
    calls = []  # coordinates of every directions request

    def handler(request):
        path = unquote(request.url.path)
        if "geocode" in path:
            q = request.url.params["q"]
            if q not in PLACES:
                return httpx.Response(200, json={"features": []})
            lon, lat = PLACES[q]
            return httpx.Response(
                200,
                json={
                    "features": [
                        {
                            "geometry": {"coordinates": [lon, lat]},
                            "properties": {"full_address": q},
                        }
                    ]
                },
            )
        coords = [tuple(map(float, p.split(","))) for p in path.rsplit("/", 1)[1].split(";")]
        calls.append(coords)
        if len(coords) == 2:
            return httpx.Response(directions_status, json={"code": "Ok", "routes": primary})
        if waypoint_status != 200:
            return httpx.Response(waypoint_status, json={"message": "no route"})
        n = sum(1 for c in calls if len(c) == 3) - 1
        routes = waypoint_routes[n] if n < len(waypoint_routes) else []
        return httpx.Response(200, json={"code": "Ok", "routes": routes})

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_geocode_returns_place():
    client, _ = make_client([A])
    assert geocode("Origin, US", client) == Place("Origin, US", -90.0, 40.0)


def test_geocode_unknown_location():
    client, _ = make_client([A])
    with pytest.raises(RoutingError, match="Could not find"):
        geocode("Nowhere", client)


def test_missing_token(monkeypatch):
    monkeypatch.delenv("MAPBOX_TOKEN")
    client, _ = make_client([A])
    with pytest.raises(RoutingError, match="MAPBOX_TOKEN"):
        geocode("Origin, US", client)


def test_http_error_does_not_leak_token():
    client, _ = make_client([A], directions_status=401)
    with pytest.raises(RoutingError) as exc:
        find_routes("Origin, US", "Dest, US", client)
    assert "401" in str(exc.value)
    assert "pk.test-token" not in str(exc.value)


def test_no_route_found():
    client, _ = make_client([])
    with pytest.raises(RoutingError, match="No drivable route"):
        find_routes("Origin, US", "Dest, US", client)


def test_route_is_normalized_for_geometry():
    client, _ = make_client([A, B, W])
    route = find_routes("Origin, US", "Dest, US", client).routes[0]
    assert len(route.distances_m) == len(route.coordinates) - 1
    assert route.distance_mi == pytest.approx(sum(route.distances_m) / METERS_PER_MILE)
    cps = generate_checkpoints(
        route.coordinates, route.distances_m, route.durations_s, DEPART, 25
    )
    assert cps[-1].distance_mi == pytest.approx(route.distance_mi)
    assert cps[-1].elapsed_s == pytest.approx(route.duration_s)


def test_multi_leg_annotations_are_concatenated():
    ann = A["legs"][0]["annotation"]
    k = 10
    legs = [
        {"annotation": {"distance": ann["distance"][:k], "duration": ann["duration"][:k]}},
        {"annotation": {"distance": ann["distance"][k:], "duration": ann["duration"][k:]}},
    ]
    client, _ = make_client([{**A, "legs": legs}, B, W])
    route = find_routes("Origin, US", "Dest, US", client).routes[0]
    assert route.distances_m == pytest.approx(ann["distance"])
    assert route.durations_s == pytest.approx(ann["duration"])


def test_route_with_mismatched_annotations_is_rejected():
    ann = A["legs"][0]["annotation"]
    bad = {
        **A,
        "legs": [{"annotation": {"distance": ann["distance"][:-1], "duration": ann["duration"][:-1]}}],
    }
    client, _ = make_client([bad])
    with pytest.raises(RoutingError, match="No drivable route"):
        find_routes("Origin, US", "Dest, US", client)


def test_three_routes_from_mapbox_need_no_extra_calls():
    client, calls = make_client([A, B, W])
    result = find_routes("Origin, US", "Dest, US", client)
    assert len(result.routes) == 3
    assert len(calls) == 1
    assert result.notes == []


def test_third_route_via_waypoint_on_the_opposite_side():
    client, calls = make_client([A, B], waypoint_routes=[[W]])
    result = find_routes("Origin, US", "Dest, US", client)
    assert [r.id for r in result.routes] == ["route-1", "route-2", "route-3"]
    assert [r.source for r in result.routes] == ["mapbox-alternative"] * 2 + ["waypoint-detour"]
    assert len(calls) == 2 and len(calls[1]) == 3
    assert calls[1][0] == O and calls[1][2] == D
    wp_lon, wp_lat = calls[1][1]
    assert wp_lon < -90.2  # west, away from B which bulges east
    assert wp_lat == pytest.approx(41.0, abs=0.2)
    assert result.notes == []


def test_duplicate_waypoint_route_is_rejected():
    client, calls = make_client([A, B], waypoint_routes=[A, A])
    result = find_routes("Origin, US", "Dest, US", client)
    assert len(result.routes) == 2
    assert len(calls) == 3  # 1 primary + 2 waypoint attempts, then stop
    assert any("2 route" in n for n in result.notes)


def test_much_slower_waypoint_route_is_rejected():
    slow = fake_route([O, (-90.4, 41.0), D], speed=10)
    client, _ = make_client([A, B], waypoint_routes=[slow, slow])
    result = find_routes("Origin, US", "Dest, US", client)
    assert len(result.routes) == 2
    assert result.notes


def test_waypoint_api_error_is_tolerated():
    client, calls = make_client([A, B], waypoint_status=422)
    result = find_routes("Origin, US", "Dest, US", client)
    assert len(result.routes) == 2
    assert len(calls) == 3