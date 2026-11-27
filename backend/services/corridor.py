"""Hourly weather risk along a route corridor: the data behind the 48-hour heatmap.

This is a forecast SNAPSHOT (weather at sample points along the route at each hour from a
reference time). It is independent of the ETA-based route analysis and never changes the
route recommendation. Risk uses the same engine and load rules as route analysis, and
missing forecasts are None (Unknown), never Low.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from services.risk import assess_risk
from services.weather import FORECAST_HOURS, OK, CheckpointWeather, fetch_hourly_forecast

SAMPLE_SPACING_MI = 25.0
MAX_SAMPLES = 120

Fetcher = Callable[[Sequence[tuple[float, float]], datetime, int], list[list[CheckpointWeather]]]


@dataclass(frozen=True)
class RoutePoint:
    lat: float
    lon: float
    distance_mi: float


@dataclass(frozen=True)
class CorridorPoint:
    lat: float
    lon: float
    distance_mi: float
    risk: list[int | None]  # 0 (Low) .. 4 (No Travel) per hour; None = unknown
    gust_mph: list[float | None]
    rain_in_hr: list[float | None]
    snow_in_hr: list[float | None]


@dataclass(frozen=True)
class CorridorForecast:
    reference_time: datetime
    hours: int
    points: list[CorridorPoint]
    unknown_cells: int
    total_cells: int


def current_hour(now: datetime | None = None) -> datetime:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return moment.replace(minute=0, second=0, microsecond=0)


def sample_points(points: Sequence[RoutePoint]) -> list[RoutePoint]:
    """Thin route points to about one per SAMPLE_SPACING_MI, never more than MAX_SAMPLES.

    The first and last points are always kept.
    """
    if len(points) <= 2:
        return list(points)
    total = points[-1].distance_mi - points[0].distance_mi
    spacing = max(SAMPLE_SPACING_MI, total / (MAX_SAMPLES - 2))
    kept = [points[0]]
    for point in points[1:-1]:
        if point.distance_mi - kept[-1].distance_mi >= spacing - 1e-9:
            kept.append(point)
    kept.append(points[-1])
    return kept


def forecast_corridor(
    points: Sequence[RoutePoint],
    load_lb: float,
    reference_time: datetime,
    fetcher: Fetcher | None = None,
) -> CorridorForecast:
    samples = sample_points(points)
    fetch = fetcher or fetch_hourly_forecast
    forecasts = fetch([(p.lat, p.lon) for p in samples], reference_time, FORECAST_HOURS)

    corridor: list[CorridorPoint] = []
    unknown = 0
    for sample, hourly in zip(samples, forecasts):
        risk: list[int | None] = []
        gust: list[float | None] = []
        rain: list[float | None] = []
        snow: list[float | None] = []
        for w in hourly:
            if w.status == OK:
                level = assess_risk(w.gust_mph, w.rain_in_hr, w.snow_in_hr, load_lb).level
                risk.append(int(level))
                gust.append(w.gust_mph)
                rain.append(w.rain_in_hr)
                snow.append(w.snow_in_hr)
            else:
                unknown += 1
                risk.append(None)
                gust.append(None)
                rain.append(None)
                snow.append(None)
        corridor.append(CorridorPoint(sample.lat, sample.lon, sample.distance_mi, risk, gust, rain, snow))
    return CorridorForecast(
        reference_time, FORECAST_HOURS, corridor, unknown, len(samples) * (FORECAST_HOURS + 1)
    )