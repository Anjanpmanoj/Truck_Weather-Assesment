"""Trip analysis: checkpoints, ETA-based weather, risk, miles per level, recommendation.

Policies:
- Each checkpoint represents half the gap to each neighbour (origin/destination get
  half a gap), so represented miles always sum to the route length.
- Checkpoints with no usable forecast are never assumed safe: they are reported as
  `unknown_mi` and counted as HIGH for average risk and ranking.
- Ranking key (lower is better): any No Travel at all, No Travel miles, Severe miles,
  High + unknown miles, average risk, duration. Miles are rounded to whole miles, average
  risk to 0.1 and duration to minutes, so trivial differences count as ties.
- A route with No Travel conditions is never presented as safe.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from services.geometry import Checkpoint, generate_checkpoints
from services.risk import RiskLevel, assess_risk
from services.routing import Place, Route, find_routes
from services.weather import OK, OUT_OF_RANGE, CheckpointWeather, fetch_checkpoint_weather

UNKNOWN_AS = RiskLevel.HIGH  # how unknown weather is counted for ranking and averages


@dataclass(frozen=True)
class CheckpointAnalysis:
    checkpoint: Checkpoint
    weather: CheckpointWeather
    level: RiskLevel | None  # None: no usable forecast
    rule: str  # what caused the level (or why it is unknown)
    represented_mi: float


@dataclass(frozen=True)
class RouteAnalysis:
    route: Route
    checkpoints: list[CheckpointAnalysis]
    miles_by_level: dict[RiskLevel, float]
    unknown_mi: float
    avg_risk: float  # distance-weighted, 0 (Low) to 4 (No Travel)

    @property
    def total_mi(self) -> float:
        return sum(c.represented_mi for c in self.checkpoints)

    @property
    def has_no_travel(self) -> bool:
        return any(c.level is RiskLevel.NO_TRAVEL for c in self.checkpoints)

    @property
    def all_unknown(self) -> bool:
        return all(c.level is None for c in self.checkpoints)

    @property
    def arrival(self) -> datetime:
        return self.checkpoints[-1].checkpoint.eta


@dataclass(frozen=True)
class Recommendation:
    route_id: str
    safe: bool  # False when the recommended route still has No Travel conditions
    explanation: str
    warnings: list[str]


@dataclass(frozen=True)
class TripAnalysis:
    routes: list[RouteAnalysis]
    recommendation: Recommendation
    notes: list[str]
    origin: Place | None = None
    destination: Place | None = None


def represented_miles(distances: Sequence[float]) -> list[float]:
    """Miles each checkpoint stands for: half the gap to each neighbour."""
    last = len(distances) - 1
    result = []
    for i, d in enumerate(distances):
        before = (d - distances[i - 1]) / 2 if i > 0 else 0.0
        after = (distances[i + 1] - d) / 2 if i < last else 0.0
        result.append(before + after)
    return result


def _assess(weather: CheckpointWeather, load_lb: float) -> tuple[RiskLevel | None, str]:
    if weather.status != OK:
        reason = (
            "No forecast for this arrival time"
            if weather.status == OUT_OF_RANGE
            else "Forecast data missing"
        )
        return None, f"{reason}: treated as High risk, not as safe"
    result = assess_risk(weather.gust_mph, weather.rain_in_hr, weather.snow_in_hr, load_lb)
    return result.level, result.rule


def analyze_route(
    route: Route,
    checkpoints: Sequence[Checkpoint],
    weather: Sequence[CheckpointWeather],
    load_lb: float,
) -> RouteAnalysis:
    miles = represented_miles([c.distance_mi for c in checkpoints])
    by_level = {level: 0.0 for level in RiskLevel}
    unknown = 0.0
    items: list[CheckpointAnalysis] = []
    for cp, wx, mi in zip(checkpoints, weather, miles):
        level, rule = _assess(wx, load_lb)
        items.append(CheckpointAnalysis(cp, wx, level, rule, mi))
        if level is None:
            unknown += mi
        else:
            by_level[level] += mi
    total = sum(miles)
    weighted = sum(int(lv) * mi for lv, mi in by_level.items()) + int(UNKNOWN_AS) * unknown
    avg = weighted / total if total > 0 else 0.0
    return RouteAnalysis(route, items, by_level, unknown, avg)


def rank_key(a: RouteAnalysis) -> tuple:
    """Lower is better. See the module docstring for the tolerance rules."""
    return (
        1 if a.has_no_travel else 0,
        round(a.miles_by_level[RiskLevel.NO_TRAVEL]),
        round(a.miles_by_level[RiskLevel.SEVERE]),
        round(a.miles_by_level[RiskLevel.HIGH] + a.unknown_mi),
        round(a.avg_risk, 1),
        round(a.route.duration_s / 60),
    )


def _label(route: Route) -> str:
    return route.id.replace("-", " ").capitalize()


def _fmt_minutes(seconds: float) -> str:
    hours, minutes = divmod(round(seconds / 60), 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def _stats(a: RouteAnalysis) -> str:
    return (
        f"{a.miles_by_level[RiskLevel.SEVERE]:.0f} Severe and "
        f"{a.miles_by_level[RiskLevel.HIGH]:.0f} High-risk miles, "
        f"average risk {a.avg_risk:.1f} out of 4"
    )


def _compare(analyses: Sequence[RouteAnalysis], keys: Sequence[tuple], best_i: int) -> str:
    best = analyses[best_i]
    label = _label(best.route)
    fastest_i = min(range(len(analyses)), key=lambda i: (analyses[i].route.duration_s, i))
    if best_i == fastest_i:
        if all(k[:-1] == keys[0][:-1] for k in keys):
            return f"Weather risk is similar on all routes, so {label}, the fastest, was chosen."
        return f"{label} is both the fastest route and the lowest-risk route."

    fast_label = _label(analyses[fastest_i].route)
    kb, kf = keys[best_i], keys[fastest_i]
    diff = next((i for i in range(5) if kb[i] != kf[i]), None)
    if diff is None:
        return f"Weather risk and travel time are essentially equal; {label} was chosen."
    reasons = {
        0: f"it avoids No Travel conditions that the fastest route ({fast_label}) has",
        1: f"it has {kb[1]} mi of No Travel conditions versus {kf[1]} mi on the fastest route ({fast_label})",
        2: f"it has {kb[2]} Severe miles versus {kf[2]} on the fastest route ({fast_label})",
        3: f"it has {kb[3]} High-risk miles versus {kf[3]} on the fastest route ({fast_label})",
        4: f"it has a lower average risk ({kb[4]:.1f} versus {kf[4]:.1f} on the fastest route, {fast_label})",
    }
    extra = best.route.duration_s - analyses[fastest_i].route.duration_s
    timing = f"It takes {_fmt_minutes(extra)} longer." if extra >= 60 else "Travel time is about the same."
    return f"{label} is recommended because {reasons[diff]}. {timing}"


def recommend(analyses: Sequence[RouteAnalysis]) -> Recommendation:
    if not analyses:
        raise ValueError("no routes to recommend from")
    keys = [rank_key(a) for a in analyses]
    best_i = min(range(len(analyses)), key=lambda i: (keys[i], i))  # ties: earlier route
    best = analyses[best_i]
    label = _label(best.route)
    safe = not best.has_no_travel
    warnings: list[str] = []

    if not safe:  # clean routes rank first, so every route has No Travel conditions
        explanation = (
            "No route is safe at this departure time: every route has No Travel conditions. "
            f"{label} has the least ({keys[best_i][1]} mi)."
        )
        warnings.append("Consider departing at a different time.")
    elif all(a.all_unknown for a in analyses):
        explanation = (
            f"No forecast is available for this departure time, so {label} was chosen "
            "on travel time alone."
        )
    elif len(analyses) == 1:
        explanation = f"{label} is the only available route: {_stats(best)}."
    else:
        explanation = _compare(analyses, keys, best_i)

    if best.unknown_mi > 0:
        warnings.append(
            f"{best.unknown_mi:.0f} of {best.total_mi:.0f} mi on {label} has no forecast "
            "data; it was treated as High risk."
        )
    return Recommendation(best.route.id, safe, explanation, warnings)


def analyze_routes(
    routes: Sequence[Route],
    departure: datetime,
    load_lb: float,
    interval_miles: float,
    weather_fetcher: Callable[[Sequence[Checkpoint]], list[CheckpointWeather]] | None = None,
) -> TripAnalysis:
    """Checkpoints, weather (one batched fetch for all routes), risk and recommendation."""
    if not routes:
        raise ValueError("no routes to analyze")
    fetch = weather_fetcher or fetch_checkpoint_weather
    per_route = [
        generate_checkpoints(r.coordinates, r.distances_m, r.durations_s, departure, interval_miles)
        for r in routes
    ]
    flat = [cp for cps in per_route for cp in cps]
    weather = fetch(flat)
    if len(weather) != len(flat):
        raise ValueError("weather results do not match the checkpoints")

    analyses: list[RouteAnalysis] = []
    start = 0
    for route, cps in zip(routes, per_route):
        analyses.append(analyze_route(route, cps, weather[start : start + len(cps)], load_lb))
        start += len(cps)
    return TripAnalysis(analyses, recommend(analyses), notes=[])


def analyze_trip(
    origin: str,
    destination: str,
    departure: datetime,
    load_lb: float,
    interval_miles: float,
) -> TripAnalysis:
    """Full pipeline from place names. RoutingError / WeatherError propagate to the caller."""
    found = find_routes(origin, destination)
    result = analyze_routes(found.routes, departure, load_lb, interval_miles)
    return replace(
        result, notes=list(found.notes), origin=found.origin, destination=found.destination
    )