import logging

from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from services.analysis import analyze_trip
from services.corridor import RoutePoint, current_hour, forecast_corridor
from services.routing import LocationNotFound, NoRouteFound, RoutingError
from services.weather import WeatherError

from .serializers import (
    AnalyzeRequestSerializer,
    CorridorRequestSerializer,
    serialize_corridor,
    serialize_trip,
)

logger = logging.getLogger(__name__)


def error_response(status: int, code: str, message: str, details=None) -> Response:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return Response(body, status=status)


def failure_response(exc: Exception) -> Response:
    """Map a service failure to an HTTP error without leaking internals."""
    if isinstance(exc, LocationNotFound):
        return error_response(422, "location_not_found", str(exc))
    if isinstance(exc, NoRouteFound):
        return error_response(422, "no_route", str(exc))
    if isinstance(exc, RoutingError):
        logger.warning("Routing failed: %s", exc)
        return error_response(
            502, "routing_unavailable", "The routing service is currently unavailable. Please try again."
        )
    if isinstance(exc, WeatherError):
        logger.warning("Weather failed: %s", exc)
        return error_response(
            502, "weather_unavailable", "The weather service is currently unavailable. Please try again."
        )
    logger.error("Unexpected error", exc_info=exc)  # last line of defence: no trace to the client
    return error_response(500, "internal_error", "Something went wrong while processing this request.")


class JsonApiView(APIView):
    authentication_classes: list = []
    permission_classes: list = []
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]


class AnalyzeView(JsonApiView):
    def post(self, request):
        serializer = AnalyzeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(400, "invalid_input", "Some inputs are invalid.", serializer.errors)
        params = serializer.validated_data
        try:
            trip = analyze_trip(
                origin=params["origin"],
                destination=params["destination"],
                departure=params["departure_time"],
                load_lb=params["load_weight"],
                interval_miles=params["interval_miles"],
            )
            body = serialize_trip(
                trip, params["departure_time"], params["load_weight"], params["interval_miles"]
            )
        except Exception as exc:
            return failure_response(exc)
        return Response(body)


class ForecastCorridorView(JsonApiView):
    def post(self, request):
        serializer = CorridorRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(400, "invalid_input", "Some inputs are invalid.", serializer.errors)
        params = serializer.validated_data
        try:
            result = forecast_corridor(
                points=[RoutePoint(**p) for p in params["points"]],
                load_lb=params["load_weight"],
                reference_time=params.get("reference_time") or current_hour(),
            )
            body = serialize_corridor(result)
        except Exception as exc:
            return failure_response(exc)
        return Response(body)
class HealthView(JsonApiView):
    """Cheap liveness check for Render and for waking a sleeping instance. No external calls."""

    def get(self, request):
        return Response({"status": "ok"})    