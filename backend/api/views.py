import logging

from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from services.analysis import analyze_trip
from services.routing import LocationNotFound, NoRouteFound, RoutingError
from services.weather import WeatherError

from .serializers import AnalyzeRequestSerializer, serialize_trip

logger = logging.getLogger(__name__)


def error_response(status: int, code: str, message: str, details=None) -> Response:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return Response(body, status=status)


class AnalyzeView(APIView):
    authentication_classes: list = []
    permission_classes: list = []
    parser_classes = [JSONParser]
    renderer_classes = [JSONRenderer]

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
        except LocationNotFound as exc:
            return error_response(422, "location_not_found", str(exc))
        except NoRouteFound as exc:
            return error_response(422, "no_route", str(exc))
        except RoutingError as exc:
            logger.warning("Routing failed: %s", exc)
            return error_response(
                502, "routing_unavailable",
                "The routing service is currently unavailable. Please try again.",
            )
        except WeatherError as exc:
            logger.warning("Weather failed: %s", exc)
            return error_response(
                502, "weather_unavailable",
                "The weather service is currently unavailable. Please try again.",
            )
        except Exception:  # last line of defence: never leak a trace to the client
            logger.exception("Unexpected error while analyzing a trip")
            return error_response(
                500, "internal_error", "Something went wrong while analyzing this trip."
            )
        return Response(body)