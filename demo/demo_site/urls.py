from django.urls import path

from tokenguard.django import rate_limit

from . import views

urlpatterns = [
    path("health/", views.health),
    path("api/ping/", views.ping),
    path("api/report/", views.report),
    path("api/config/", views.config),
    path("login/", views.login),
    path(
        "api/chat/",
        rate_limit(capacity=10, refill_rate=0.1, key="ip")(views.ChatView.as_view()),
    ),
    path("api/summary/", views.SummaryView.as_view()),
]
