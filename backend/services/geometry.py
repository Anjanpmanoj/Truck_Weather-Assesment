"""Route geometry helpers: cumulative distance/time, interpolation, checkpoints.

Pure functions, no I/O. Input is a Mapbox-style route:
- coordinates: list of [lon, lat]
- distances_m / durations_s: one value per segment (len = len(coordinates) - 1)

ETAs come from cumulative segment durations, never a constant average speed.
Positions are interpolated linearly inside a segment (segments are short).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import accumulate

METERS_PER_MILE = 1609.344


@dataclass(frozen=True)
class Checkpoint:
    index: int
    distance_mi: float  # miles from the origin along the route
    elapsed_s: float  # seconds from departure
    lat: float
    lon: float
    eta: datetime  # timezone-aware, UTC


def cumulative_profile(
    distances_m: Sequence[float], durations_s: Sequence[float]
) -> tuple[list[float], list[float]]:
    """Cumulative miles and seconds at every route point (starts at 0)."""
    miles = [0.0, *accumulate(d / METERS_PER_MILE for d in distances_m)]
    seconds = [0.0, *accumulate(float(s) for s in durations_s)]
    return miles, seconds


def point_at_distance(
    coordinates: Sequence[Sequence[float]],
    cum_miles: Sequence[float],
    cum_seconds: Sequence[float],
    target_mi: float,
) -> tuple[float, float, float]:
    """Return (lat, lon, elapsed_s) at target_mi along the route.

    Targets at or beyond the ends are clamped to the origin / destination.
    """
    if target_mi <= 0:
        lon, lat = coordinates[0][0], coordinates[0][1]
        return lat, lon, 0.0
    if target_mi >= cum_miles[-1]:
        lon, lat = coordinates[-1][0], coordinates[-1][1]
        return lat, lon, cum_seconds[-1]

    i = bisect_right(cum_miles, target_mi) - 1  # segment i: point i -> point i+1
    span = cum_miles[i + 1] - cum_miles[i]  # > 0 because target is inside it
    frac = (target_mi - cum_miles[i]) / span

    lon0, lat0 = coordinates[i][0], coordinates[i][1]
    lon1, lat1 = coordinates[i + 1][0], coordinates[i + 1][1]
    elapsed = cum_seconds[i] + frac * (cum_seconds[i + 1] - cum_seconds[i])
    return lat0 + frac * (lat1 - lat0), lon0 + frac * (lon1 - lon0), elapsed


def generate_checkpoints(
    coordinates: Sequence[Sequence[float]],
    distances_m: Sequence[float],
    durations_s: Sequence[float],
    departure: datetime,
    interval_miles: float,
) -> list[Checkpoint]:
    """Checkpoints at 0, N, 2N, ... miles, always ending at the destination."""
    if len(coordinates) < 2:
        raise ValueError("route needs at least 2 coordinates")
    if len(distances_m) != len(coordinates) - 1 or len(durations_s) != len(distances_m):
        raise ValueError("distances/durations must have one value per route segment")
    if interval_miles <= 0:
        raise ValueError("interval_miles must be positive")
    if departure.tzinfo is None:
        raise ValueError("departure must be timezone-aware")

    cum_miles, cum_seconds = cumulative_profile(distances_m, durations_s)
    total = cum_miles[-1]
    if total <= 0:
        raise ValueError("route has zero length")

    targets = [0.0]
    k = 1
    while k * interval_miles < total - 1e-9:  # skip a duplicate of the destination
        targets.append(k * interval_miles)
        k += 1
    targets.append(total)

    departure_utc = departure.astimezone(timezone.utc)
    checkpoints: list[Checkpoint] = []
    for index, target in enumerate(targets):
        lat, lon, elapsed = point_at_distance(coordinates, cum_miles, cum_seconds, target)
        checkpoints.append(
            Checkpoint(
                index=index,
                distance_mi=target,
                elapsed_s=elapsed,
                lat=lat,
                lon=lon,
                eta=departure_utc + timedelta(seconds=elapsed),
            )
        )
    return checkpoints