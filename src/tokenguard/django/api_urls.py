from django.urls import path

from tokenguard.django import api

urlpatterns = [
    path("session/", api.SessionView.as_view()),
    path("login/", api.LoginView.as_view()),
    path("logout/", api.LogoutView.as_view()),
    path("stats/", api.StatsView.as_view()),
    path("consumers/", api.ConsumersView.as_view()),
    path("buckets/<path:key>/", api.BucketView.as_view()),
    path("rules/", api.RuleListView.as_view()),
    path("rules/<path:scope>/", api.RuleDetailView.as_view()),
]
