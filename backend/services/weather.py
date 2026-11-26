"""Open-Meteo hourly forecast lookup at each checkpoint's ETA.

- Requests are batched (many coordinates per call) and de-duplicated: coordinates are
  rounded to 2 decimals and shared points are fetched once.
- Wind and gusts are instantaneous, so they are linearly interpolated between hours.
- Rain and snowfall are totals for the PRECEDING hour (value labelled 14:00 covers
  13:00-14:00), so we use the hourly bucket the ETA falls in instead of interpolating.
- Rain is `rain + showers`. Units are requested as mph / inch, so hourly totals are in/hr.
- `gust_mph` is what risk.assess_risk should receive; `wind_mph` is for display.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from services.geometry import Checkpoint

API_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
WIND_UNITS = ("mp/h", "mph")
CHUNK_SIZE = 50  # locations per request
MAX_PAST_DAYS = 92
MAX_FORECAST_DAYS = 16
TIMEOUT = 20.0

OK = "ok"
OUT_OF_RANGE = "out_of_range"  # ETA outside the available forecast window
MISSING = "missing"  # forecast exists but a needed value is null


class WeatherError(Exception):
    """The weather service failed or returned something unusable."""


@dataclass(frozen=True)
class CheckpointWeather:
    status: str  # OK, OUT_OF_RANGE or MISSING
    wind_mph: float | None = None  # sustained, for display
    gust_mph: float | None = None  # used for risk
    rain_in_hr: float | None = None
    snow_in_hr: float | None = None


@dataclass(frozen=True)
class _Series:
    start: datetime  # UTC time of the first hourly value
    wind: list[float | None]
    gust: list[float | None]
    rain: list[float | None]  # rain + showers
    snow: list[float | None]


@contextmanager
def _session(client: httpx.Client | None) -> Iterator[httpx.Client]:
    if client is not None:
        yield client
    else:
        with httpx.Client(timeout=TIMEOUT) as owned:
            yield owned


def _key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, 2), round(lon, 2))


def _parse_location(loc: dict) -> _Series:
    try:
        units, hourly = loc["hourly_units"], loc["hourly"]
        for name in ("wind_speed_10m", "wind_gusts_10m"):
            if units[name] not in WIND_UNITS:
                raise WeatherError(f"Unexpected unit for {name}: {units[name]!r}")
        for name in ("rain", "snowfall"):
            if units[name] != "inch":
                raise WeatherError(f"Unexpected unit for {name}: {units[name]!r}")
        times = hourly["time"]
        showers = hourly.get("showers") or [0.0] * len(times)
        rain = [None if r is None else r + (s or 0.0) for r, s in zip(hourly["rain"], showers)]
        return _Series(
            start=datetime.fromisoformat(times[0]).replace(tzinfo=timezone.utc),
            wind=hourly["wind_speed_10m"],
            gust=hourly["wind_gusts_10m"],
            rain=rain,
            snow=hourly["snowfall"],
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WeatherError("Unexpected response format from the weather service") from exc


def _fetch_chunk(
    client: httpx.Client,
    keys: Sequence[tuple[float, float]],
    past_days: int,
    forecast_days: int,
) -> list[_Series]:
    params = {
        "latitude": ",".join(f"{lat:.2f}" for lat, _ in keys),
        "longitude": ",".join(f"{lon:.2f}" for _, lon in keys),
        "hourly": HOURLY_VARS,
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "UTC",
        "past_days": past_days,
        "forecast_days": forecast_days,
    }
    try:
        response = client.get(API_URL, params=params)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise WeatherError(f"Weather service request failed: {exc}") from exc
    if isinstance(data, dict):  # a single location comes back as an object, not a list
        data = [data]
    if not isinstance(data, list) or len(data) != len(keys):
        raise WeatherError("Weather service returned an unexpected number of locations")
    return [_parse_location(loc) for loc in data]


def _lerp(a: float | None, b: float | None, frac: float) -> float | None:
    if a is None:
        return b
    if b is None:
        return a
    return a + frac * (b - a)


def _weather_at(series: _Series, eta: datetime) -> CheckpointWeather:
    hours = (eta - series.start).total_seconds() / 3600
    last = len(series.wind) - 1
    if hours < 0 or hours > last:
        return CheckpointWeather(OUT_OF_RANGE)
    i = math.floor(hours)
    nxt = min(i + 1, last)  # next hourly point; also the label of the hour containing eta
    frac = hours - i
    wind = _lerp(series.wind[i], series.wind[nxt], frac)
    gust = _lerp(series.gust[i], series.gust[nxt], frac)
    rain, snow = series.rain[nxt], series.snow[nxt]
    if None in (wind, gust, rain, snow):
        return CheckpointWeather(MISSING)
    return CheckpointWeather(OK, wind, gust, rain, snow)


def fetch_checkpoint_weather(
    checkpoints: Sequence[Checkpoint],
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> list[CheckpointWeather]:
    """Weather at each checkpoint's ETA, in the same order as `checkpoints`.

    Pass checkpoints from all routes at once so shared points are fetched once.
    """
    if not checkpoints:
        return []
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    etas = [c.eta for c in checkpoints]
    first_date = min(etas).astimezone(timezone.utc).date()
    # +1h: the last ETA needs the hourly value after it
    last_date = (max(etas).astimezone(timezone.utc) + timedelta(hours=1)).date()

    if (last_date - today).days < -MAX_PAST_DAYS or (first_date - today).days >= MAX_FORECAST_DAYS:
        return [CheckpointWeather(OUT_OF_RANGE) for _ in checkpoints]
    past_days = min(max((today - first_date).days, 0), MAX_PAST_DAYS)
    forecast_days = min(max((last_date - today).days + 1, 1), MAX_FORECAST_DAYS)

    keys = list(dict.fromkeys(_key(c.lat, c.lon) for c in checkpoints))
    series_by_key: dict[tuple[float, float], _Series] = {}
    with _session(client) as http:
        for i in range(0, len(keys), CHUNK_SIZE):
            chunk = keys[i : i + CHUNK_SIZE]
            for key, series in zip(chunk, _fetch_chunk(http, chunk, past_days, forecast_days)):
                series_by_key[key] = series
    return [_weather_at(series_by_key[_key(c.lat, c.lon)], c.eta) for c in checkpoints]