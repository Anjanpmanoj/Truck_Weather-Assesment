from django.urls import re_path

from .views import AnalyzeView

urlpatterns = [
    re_path(r"^analyze/?$", AnalyzeView.as_view(), name="analyze"),
]