"""Request validation and JSON shaping for the analyze endpoint."""

from __future__ import annotations

import math
from bisect import bisect_right
from datetime import datetime, timedelta, timezone as dt_timezone

from rest_framework import serializers

from services.analysis import CheckpointAnalysis, RouteAnalysis, TripAnalysis
from services.geometry import cumulative_profile
from services.risk import RiskLevel
from services.routing import Place
from services.weather import MAX_FORECAST_DAYS

MAX_LOAD_LB = 200_000  # sanity limit, not a legal limit
INTERVAL_CHOICES = (10, 25, 50)


class AwareDateTimeField(serializers.DateTimeField):
    """ISO 8601 datetime that must include a timezone; normalized to UTC."""

    def enforce_timezone(self, value):
        if value.tzinfo is None:
            raise serializers.ValidationError(
                "Include a timezone offset, e.g. 2026-11-27T09:00:00-06:00 or ...Z."
            )
        return value.astimezone(dt_timezone.utc)


class AnalyzeRequestSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=200)
    destination = serializers.CharField(max_length=200)
    departure_time = AwareDateTimeField()
    load_weight = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(choices=INTERVAL_CHOICES)

    def validate_load_weight(self, value):
        if not math.isfinite(value):  # "nan" passes the range validators
            raise serializers.ValidationError("A valid number is required.")
        return value

    def validate_departure_time(self, value):
        days = MAX_FORECAST_DAYS - 1
        if value > datetime.now(dt_timezone.utc) + timedelta(days=days):
            raise serializers.ValidationError(
                f"Departure must be within the next {days} days (the weather forecast horizon)."
            )
        return value

    def validate(self, attrs):
        if attrs["origin"].casefold() == attrs["destination"].casefold():
            raise serializers.ValidationError(
                {"destination": "Origin and destination must be different."}
            )
        return attrs


def _iso(dt: datetime) -> str:
    return dt.astimezone(dt_timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _r(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _level_key(level: RiskLevel | None) -> str:
    return "unknown" if level is None else level.name.lower()


def _place(place: Place | None) -> dict | None:
    if place is None:
        return None
    return {"name": place.name, "lat": round(place.lat, 5), "lon": round(place.lon, 5)}


def _checkpoint(item: CheckpointAnalysis) -> dict:
    cp, wx = item.checkpoint, item.weather
    return {
        "index": cp.index,
        "distance_mi": round(cp.distance_mi, 2),
        "represented_mi": round(item.represented_mi, 2),
        "lat": round(cp.lat, 5),
        "lon": round(cp.lon, 5),
        "eta": _iso(cp.eta),
        "weather": {
            "status": wx.status,
            "wind_mph": _r(wx.wind_mph, 1),
            "gust_mph": _r(wx.gust_mph, 1),
            "rain_in_hr": _r(wx.rain_in_hr, 3),
            "snow_in_hr": _r(wx.snow_in_hr, 3),
        },
        "risk": {
            "level": _level_key(item.level),
            "value": None if item.level is None else int(item.level),
            "label": "Unknown" if item.level is None else item.level.label,
            "rule": item.rule,
        },
    }


def _segments(a: RouteAnalysis) -> list[dict]:
    """Stretches of the route around each checkpoint, as index ranges into the geometry.

    Boundaries are the midpoints between checkpoints, so segments are contiguous and
    each takes the risk level of the checkpoint it surrounds.
    """
    route = a.route
    cum_miles, _ = cumulative_profile(route.distances_m, route.durations_s)
    last = len(route.coordinates) - 1
    at = [c.checkpoint.distance_mi for c in a.checkpoints]
    bounds = [0.0] + [(at[i - 1] + at[i]) / 2 for i in range(1, len(at))] + [cum_miles[-1]]

    def index_at(miles: float) -> int:
        return min(max(bisect_right(cum_miles, miles) - 1, 0), last)

    segments = []
    for i, item in enumerate(a.checkpoints):
        start = index_at(bounds[i])
        end = max(index_at(bounds[i + 1]), min(start + 1, last))
        segments.append(
            {
                "level": _level_key(item.level),
                "start_index": start,
                "end_index": end,
                "start_mi": round(bounds[i], 2),
                "end_mi": round(bounds[i + 1], 2),
            }
        )
    return segments


def _route(a: RouteAnalysis, recommended_id: str) -> dict:
    route = a.route
    miles = {level.name.lower(): round(a.miles_by_level[level], 2) for level in RiskLevel}
    miles["unknown"] = round(a.unknown_mi, 2)
    return {
        "id": route.id,
        "label": route.id.replace("-", " ").capitalize(),
        "source": route.source,
        "recommended": route.id == recommended_id,
        "distance_mi": round(route.distance_mi, 2),
        "duration_s": round(route.duration_s),
        "arrival_time": _iso(a.arrival),
        "summary": {
            "miles_by_level": miles,
            "avg_risk": round(a.avg_risk, 2),
            "has_no_travel": a.has_no_travel,
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [[round(x, 5), round(y, 5)] for x, y in route.coordinates],
        },
        "segments": _segments(a),
        "checkpoints": [_checkpoint(c) for c in a.checkpoints],
    }


def serialize_trip(
    trip: TripAnalysis, departure: datetime, load_weight: float, interval_miles: int
) -> dict:
    rec = trip.recommendation
    return {
        "origin": _place(trip.origin),
        "destination": _place(trip.destination),
        "request": {
            "departure_time": _iso(departure),
            "load_weight": load_weight,
            "interval_miles": interval_miles,
        },
        "recommendation": {
            "route_id": rec.route_id,
            "safe": rec.safe,
            "explanation": rec.explanation,
            "warnings": list(rec.warnings),
        },
        "notes": list(trip.notes),
        "routes": [_route(a, rec.route_id) for a in trip.routes],
    }