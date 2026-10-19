"""Staff-only REST endpoints for the dashboard (Django REST Framework).

    path("tokenguard/", include("tokenguard.django.api_urls"))

        GET    stats/?seconds=60&step=1      the numbers behind the chart
        GET    consumers/?n=10&by=tokens     who is using the most
        GET    buckets/<scope>:<id>/         one key's bucket right now
        GET    rules/                        every rule, configured and live
        PUT    rules/<scope>/                change a rule live
        DELETE rules/<scope>/                put a rule back to its settings

Only staff users (is_staff) get in: a logged-in session, or HTTP Basic (use
HTTPS). Everyone else gets 403. These views are exempt from rate limiting, so a
dashboard polling them never eats into a limit.
"""

from __future__ import annotations

from typing import Any

from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from tokenguard.django import admin_api
from tokenguard.django.admin_api import ApiError


def _int(request: Any, name: str, default: int) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ApiError(400, f"{name} must be a whole number") from None


class StaffView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]
    tokenguard_exempt = True  # the middleware leaves these alone

    def handle_exception(self, exc: Exception):
        if isinstance(exc, ApiError):
            return Response({"error": exc.message}, status=exc.status)
        return super().handle_exception(exc)


class StatsView(StaffView):
    def get(self, request):
        return Response(
            admin_api.stats(
                seconds=_int(request, "seconds", 60),
                step=_int(request, "step", 1),
                n=_int(request, "n", 5),
                minutes=_int(request, "minutes", 2),
            )
        )


class ConsumersView(StaffView):
    def get(self, request):
        return Response(
            admin_api.consumers(
                n=_int(request, "n", 10),
                minutes=_int(request, "minutes", 5),
                by=request.query_params.get("by", "tokens"),
            )
        )


class BucketView(StaffView):
    def get(self, request, key):
        return Response(admin_api.bucket(key))


class RuleListView(StaffView):
    def get(self, request):
        return Response(admin_api.list_rules())


class RuleDetailView(StaffView):
    def get(self, request, scope):
        return Response(admin_api.get_rule(scope))

    def put(self, request, scope):
        return Response(admin_api.update_rule(scope, request.data))

    def delete(self, request, scope):
        return Response(admin_api.reset_rule(scope))
