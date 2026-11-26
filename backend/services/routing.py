"""Mapbox geocoding and routing, normalized for services.geometry.

- Routes carry per-segment distances/durations so geometry.generate_checkpoints
  can compute ETAs from cumulative durations.
- Mapbox usually returns 1-2 routes. If fewer than 3, we make at most
  MAX_WAYPOINT_ATTEMPTS extra calls routed through a perpendicular waypoint and keep
  a result only if it is genuinely distinct. Routes are never duplicated or invented;
  when we end up with fewer than 3, `notes` says so.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace

import httpx

from services.geometry import METERS_PER_MILE, cumulative_profile, point_at_distance

GEOCODE_URL = "https://api.mapbox.com/search/geocode/v6/forward"
DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving"
TIMEOUT = 30.0
MAX_ROUTES = 3
MAX_WAYPOINT_ATTEMPTS = 2
MAX_OVERLAP = 0.75  # a new route may share at most this fraction of points with another
MAX_DETOUR_RATIO = 1.5  # ...and may take at most this multiple of the fastest duration
MI_PER_DEGREE = 69.0  # approximate miles per degree of latitude


class RoutingError(Exception):
    """Geocoding or routing failed."""
class LocationNotFound(RoutingError):
    """The place text matched no US location (a client error)."""


class NoRouteFound(RoutingError):
    """No drivable route exists between the two places (a client error)."""    


@dataclass(frozen=True)
class Place:
    name: str
    lon: float
    lat: float


@dataclass(frozen=True)
class Route:
    id: str
    source: str  # "mapbox-alternative" or "waypoint-detour"
    coordinates: list[list[float]]  # [lon, lat]
    distances_m: list[float]  # one per segment
    durations_s: list[float]  # one per segment
    distance_mi: float  # sum of segment distances
    duration_s: float  # sum of segment durations


@dataclass(frozen=True)
class RoutesResult:
    origin: Place
    destination: Place
    routes: list[Route]
    notes: list[str]


@contextmanager
def _session(client: httpx.Client | None) -> Iterator[httpx.Client]:
    if client is not None:
        yield client
    else:
        with httpx.Client(timeout=TIMEOUT) as owned:
            yield owned


def _token() -> str:
    token = os.environ.get("MAPBOX_TOKEN")
    if not token:
        raise RoutingError("MAPBOX_TOKEN is not set")
    return token


def _get_json(client: httpx.Client, url: str, params: dict) -> dict:
    # Never put str(exc) in the message: httpx includes the URL, which holds the token.
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise RoutingError(f"Mapbox returned HTTP {exc.response.status_code}") from None
    except (httpx.HTTPError, ValueError) as exc:
        raise RoutingError(f"Mapbox request failed ({type(exc).__name__})") from None


def geocode(query: str, client: httpx.Client | None = None) -> Place:
    with _session(client) as http:
        data = _get_json(
            http,
            GEOCODE_URL,
            {"q": query, "country": "us", "limit": 1, "access_token": _token()},
        )
    features = data.get("features") or []
    if not features:
        raise LocationNotFound(f"Could not find a US location for {query!r}")
    feature = features[0]
    lon, lat = feature["geometry"]["coordinates"][:2]
    props = feature.get("properties") or {}
    return Place(props.get("full_address") or props.get("name") or query, float(lon), float(lat))


def _parse_route(raw: dict, source: str) -> Route:
    coords = [[p[0], p[1]] for p in raw["geometry"]["coordinates"]]
    distances: list[float] = []
    durations: list[float] = []
    for leg in raw["legs"]:  # a route through a waypoint has several legs
        annotation = leg.get("annotation") or {}
        distances.extend(annotation.get("distance", []))
        durations.extend(annotation.get("duration", []))
    if len(coords) < 2 or len(distances) != len(coords) - 1 or len(durations) != len(distances):
        raise ValueError("route annotations do not match geometry")
    return Route(
        id="",
        source=source,
        coordinates=coords,
        distances_m=distances,
        durations_s=durations,
        distance_mi=sum(distances) / METERS_PER_MILE,
        duration_s=float(sum(durations)),
    )


def _fetch_routes(
    client: httpx.Client,
    points: Sequence[tuple[float, float]],  # (lon, lat)
    alternatives: bool,
    source: str,
) -> list[Route]:
    path = ";".join(f"{lon:.5f},{lat:.5f}" for lon, lat in points)
    data = _get_json(
        client,
        f"{DIRECTIONS_URL}/{path}",
        {
            "alternatives": "true" if alternatives else "false",
            "geometries": "geojson",
            "overview": "full",
            "annotations": "duration,distance",
            "access_token": _token(),
        },
    )
    routes: list[Route] = []
    for raw in data.get("routes") or []:
        try:
            routes.append(_parse_route(raw, source))
        except (KeyError, TypeError, ValueError):
            continue  # drop a malformed route rather than guess at its timing
    return routes


def _points_at(route: Route, fractions: Sequence[float]) -> list[tuple[float, float]]:
    """(lon, lat) at the given fractions of the route's length."""
    miles, seconds = cumulative_profile(route.distances_m, route.durations_s)
    points = []
    for fraction in fractions:
        lat, lon, _ = point_at_distance(route.coordinates, miles, seconds, miles[-1] * fraction)
        points.append((lon, lat))
    return points


def _candidate_waypoints(routes: Sequence[Route]) -> list[tuple[float, float]]:
    """Waypoints perpendicular to the fastest route's midpoint, best side first."""
    (lon_a, lat_a), (lon_m, lat_m), (lon_b, lat_b) = _points_at(routes[0], (0.45, 0.5, 0.55))
    scale = math.cos(math.radians(lat_m))
    dx = (lon_b - lon_a) * scale * MI_PER_DEGREE  # miles east
    dy = (lat_b - lat_a) * MI_PER_DEGREE  # miles north
    norm = math.hypot(dx, dy)
    if norm == 0:
        return []
    left = (-dy / norm, dx / norm)  # unit vector (east, north) to the left of travel
    sides = [left, (-left[0], -left[1])]
    if len(routes) > 1:  # try the side away from the existing alternative first
        lon_c, lat_c = _points_at(routes[1], (0.5,))[0]
        toward_alt = (
            (lon_c - lon_m) * scale * MI_PER_DEGREE * left[0]
            + (lat_c - lat_m) * MI_PER_DEGREE * left[1]
        )
        if toward_alt > 0:
            sides.reverse()
    offset_mi = min(max(0.15 * routes[0].distance_mi, 8.0), 40.0)
    return [
        (
            lon_m + ux * offset_mi / (MI_PER_DEGREE * scale),
            lat_m + uy * offset_mi / MI_PER_DEGREE,
        )
        for ux, uy in sides
    ]


def _rounded(route: Route) -> set[tuple[float, float]]:
    return {(round(x, 3), round(y, 3)) for x, y in route.coordinates}


def _overlap(a: Route, b: Route) -> float:
    pts_a, pts_b = _rounded(a), _rounded(b)
    return len(pts_a & pts_b) / len(pts_a)


def _is_distinct(candidate: Route, existing: Sequence[Route]) -> bool:
    fastest = min(r.duration_s for r in existing)
    if candidate.duration_s > MAX_DETOUR_RATIO * fastest:
        return False
    return all(
        max(_overlap(candidate, r), _overlap(r, candidate)) < MAX_OVERLAP for r in existing
    )


def find_routes(
    origin: str, destination: str, client: httpx.Client | None = None
) -> RoutesResult:
    """Geocode both ends and return up to 3 genuinely different routes."""
    with _session(client) as http:
        start = geocode(origin, http)
        end = geocode(destination, http)
        ends = [(start.lon, start.lat), (end.lon, end.lat)]

        routes = _fetch_routes(http, ends, True, "mapbox-alternative")[:MAX_ROUTES]
        if not routes:
            raise NoRouteFound("No drivable route found between these locations")
        from_mapbox = len(routes)

        if from_mapbox < MAX_ROUTES:
            for waypoint in _candidate_waypoints(routes)[:MAX_WAYPOINT_ATTEMPTS]:
                if len(routes) >= MAX_ROUTES:
                    break
                try:
                    found = _fetch_routes(http, [ends[0], waypoint, ends[1]], False, "waypoint-detour")
                except RoutingError:
                    continue
                if found and _is_distinct(found[0], routes):
                    routes.append(found[0])

    notes: list[str] = []
    if len(routes) < MAX_ROUTES:
        notes.append(
            f"Mapbox returned {from_mapbox} route(s) and no distinct additional route "
            f"could be generated, so {len(routes)} route(s) are shown."
        )
    routes = [replace(r, id=f"route-{i}") for i, r in enumerate(routes, start=1)]
    return RoutesResult(start, end, routes, notes)
