from django.urls import re_path

from .views import AnalyzeView, ForecastCorridorView, HealthView

urlpatterns = [
    re_path(r"^analyze/?$", AnalyzeView.as_view(), name="analyze"),
    re_path(r"^forecast-corridor/?$", ForecastCorridorView.as_view(), name="forecast-corridor"),
    re_path(r"^health/?$", HealthView.as_view(), name="health"),
]