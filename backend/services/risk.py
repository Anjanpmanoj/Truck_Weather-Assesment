"""Weather risk classification for a truck at a single checkpoint.

Pure functions only: no Django, no network, no I/O.

Assumptions (also documented in the README):
- Wind is evaluated on gusts (wind_gusts_10m), a conservative truck-safety choice.
- Boundaries are half-open, e.g. wind 25 mph is Moderate, 24.9 is Low.
- Rain: Severe is 0.50 through 1.00 in/hr inclusive; No Travel is > 1.00.
- Snow: Severe is 2.0 through 3.0 in/hr inclusive; No Travel is > 3.0.
- Load rules use strict ">" (exactly 30,000 lb or 40,000 lb does not trigger).
- On equal levels, the load rule is reported as the cause.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum

NO_TRAVEL_LOAD_LB = 30_000  # gusts 45-54 mph and load above this -> No Travel
SEVERE_LOAD_LB = 40_000  # gusts 35-44 mph and load above this -> at least Severe


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").title()


@dataclass(frozen=True)
class RiskResult:
    level: RiskLevel
    rule: str  # human-readable cause of the overall level
    wind_level: RiskLevel
    rain_level: RiskLevel
    snow_level: RiskLevel


def _validate(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a non-negative number, got {value!r}")


def classify_wind(wind_gust_mph: float) -> RiskLevel:
    _validate("wind_gust_mph", wind_gust_mph)
    if wind_gust_mph >= 55:
        return RiskLevel.NO_TRAVEL
    if wind_gust_mph >= 45:
        return RiskLevel.SEVERE
    if wind_gust_mph >= 35:
        return RiskLevel.HIGH
    if wind_gust_mph >= 25:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def classify_rain(rain_in_per_hr: float) -> RiskLevel:
    _validate("rain_in_per_hr", rain_in_per_hr)
    if rain_in_per_hr > 1.00:
        return RiskLevel.NO_TRAVEL
    if rain_in_per_hr >= 0.50:
        return RiskLevel.SEVERE
    if rain_in_per_hr >= 0.25:
        return RiskLevel.HIGH
    if rain_in_per_hr >= 0.10:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def classify_snow(snow_in_per_hr: float) -> RiskLevel:
    _validate("snow_in_per_hr", snow_in_per_hr)
    if snow_in_per_hr > 3.0:
        return RiskLevel.NO_TRAVEL
    if snow_in_per_hr >= 2.0:
        return RiskLevel.SEVERE
    if snow_in_per_hr >= 1.0:
        return RiskLevel.HIGH
    if snow_in_per_hr >= 0.5:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def _load_override(wind_gust_mph: float, load_lb: float) -> tuple[RiskLevel, str] | None:
    """Return (minimum level, rule text) if a load-weight rule applies, else None."""
    if 45 <= wind_gust_mph < 55 and load_lb > NO_TRAVEL_LOAD_LB:
        return (
            RiskLevel.NO_TRAVEL,
            f"Load rule: gusts 45-54 mph with load over {NO_TRAVEL_LOAD_LB:,} lb "
            f"({load_lb:,.0f} lb): No Travel",
        )
    if 35 <= wind_gust_mph < 45 and load_lb > SEVERE_LOAD_LB:
        return (
            RiskLevel.SEVERE,
            f"Load rule: gusts 35-44 mph with load over {SEVERE_LOAD_LB:,} lb "
            f"({load_lb:,.0f} lb): Severe",
        )
    return None


def assess_risk(
    wind_gust_mph: float,
    rain_in_per_hr: float,
    snow_in_per_hr: float,
    load_lb: float,
) -> RiskResult:
    """Overall risk at one checkpoint: the max of wind, rain, snow and load rules."""
    _validate("load_lb", load_lb)
    wind = classify_wind(wind_gust_mph)
    rain = classify_rain(rain_in_per_hr)
    snow = classify_snow(snow_in_per_hr)

    wind_text = f"Wind gusts {wind_gust_mph:g} mph: {wind.label}"
    if wind is RiskLevel.NO_TRAVEL:
        wind_text += " (55+ mph, any load)"

    # Order matters: on equal levels the first candidate wins, so load rules come first.
    candidates: list[tuple[RiskLevel, str]] = []
    override = _load_override(wind_gust_mph, load_lb)
    if override is not None:
        candidates.append(override)
    candidates.append((wind, wind_text))
    candidates.append((rain, f"Rain {rain_in_per_hr:g} in/hr: {rain.label}"))
    candidates.append((snow, f"Snow {snow_in_per_hr:g} in/hr: {snow.label}"))

    level, rule = max(candidates, key=lambda c: c[0])
    if level is RiskLevel.LOW:
        rule = "All conditions below Moderate thresholds"

    return RiskResult(level, rule, wind, rain, snow)