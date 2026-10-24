from django.urls import include, path

from tokenguard.django import rate_limit

from . import views

urlpatterns = [
    # Week 6: staff-only stats, consumers, buckets and rules for the dashboard
    path("tokenguard/", include("tokenguard.django.api_urls")),
    path("health/", views.health),
    path("api/ping/", views.ping),
    path("api/report/", views.report),
    path("api/config/", views.config),
    path("api/fixed/", views.fixed),
    path("api/keyed/", views.keyed),
    path("login/", views.login),
    path(
        "api/chat/",
        rate_limit(capacity=10, refill_rate=0.1, key="ip")(views.ChatView.as_view()),
    ),
    path("api/summary/", views.SummaryView.as_view()),
    # Week 4: the mock LLM API
    path("api/llm/chat/", views.chat),
    path("api/complete/", views.complete),
    path("api/complete-manual/", views.complete_manual),
    path("api/budgeted/", views.budgeted),
]
