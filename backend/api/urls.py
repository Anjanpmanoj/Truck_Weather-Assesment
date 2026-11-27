from django.urls import re_path

from .views import AnalyzeView, ForecastCorridorView

urlpatterns = [
    re_path(r"^analyze/?$", AnalyzeView.as_view(), name="analyze"),
    re_path(r"^forecast-corridor/?$", ForecastCorridorView.as_view(), name="forecast-corridor"),
]