"""Staff-only REST endpoints for the dashboard (Django REST Framework).

    path("tokenguard/", include("tokenguard.django.api_urls"))

        GET    stats/?seconds=60&step=1      the numbers behind the chart
        GET    consumers/?n=10&by=tokens     who is using the most
        GET    buckets/<scope>:<id>/         one key's bucket right now
        GET    rules/                        every rule, configured and live
        PUT    rules/<scope>/                change a rule live
        DELETE rules/<scope>/                put a rule back to its settings
        GET    session/                      who am I (also sets the CSRF cookie)
        POST   login/   {username, password} sign in (staff only)
        POST   logout/                       sign out

Only staff users (is_staff) get in: a logged-in session, or HTTP Basic (use
HTTPS). Everyone else gets 403. These views are exempt from rate limiting, so a
dashboard polling them never eats into a limit.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.permissions import AllowAny, IsAdminUser
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


class JsonErrors:
    """Mixin: ApiError becomes {"error": message} with its HTTP status."""

    def handle_exception(self, exc: Exception):
        if isinstance(exc, ApiError):
            return Response({"error": exc.message}, status=exc.status)
        return super().handle_exception(exc)  # type: ignore[misc]


class StaffView(JsonErrors, APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [IsAdminUser]
    tokenguard_exempt = True  # the middleware leaves these alone


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


# ---- signing in, for the dashboard (session cookie, CSRF protected) ----
def _who(request: Any) -> dict[str, Any]:
    user = request.user
    signed_in = bool(user and user.is_authenticated)
    return {
        "authenticated": signed_in,
        "staff": bool(signed_in and user.is_staff),
        "username": user.get_username() if signed_in else None,
    }


class OpenView(JsonErrors, APIView):
    """Reachable without signing in. Login is deliberately NOT exempt from the rate
    limiter: add a RULES entry for it (docs/dashboard-backend.md) so password
    guessing is limited."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]


@method_decorator(ensure_csrf_cookie, name="dispatch")
class SessionView(OpenView):
    """Who is signed in, and the CSRF cookie the page sends back on changes."""

    tokenguard_exempt = True  # the dashboard asks this on every page load

    def get(self, request):
        response = Response(_who(request))
        # ensure_csrf_cookie only asks CsrfViewMiddleware to set the cookie. A
        # project without that middleware (like the demo, whose scripts POST to
        # its API) would never get one, so set it here as well. With the
        # middleware installed this is harmless: same cookie, same name.
        response.set_cookie(
            settings.CSRF_COOKIE_NAME,
            get_token(request._request),
            max_age=settings.CSRF_COOKIE_AGE,
            secure=settings.CSRF_COOKIE_SECURE,
            samesite=settings.CSRF_COOKIE_SAMESITE,
            httponly=False,  # the page has to read it
        )
        return response


class LoginView(OpenView):
    def post(self, request):
        SessionAuthentication().enforce_csrf(request)  # a login form needs a token too
        data = request.data if isinstance(request.data, dict) else {}
        username, password = data.get("username"), data.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise ApiError(400, "send username and password")
        user = authenticate(request, username=username, password=password)
        # One message for "no such user", "wrong password" and "not staff", so the
        # response does not reveal which accounts exist.
        if user is None or not user.is_staff:
            raise ApiError(401, "invalid credentials, or not a staff account")
        login(request, user)
        return Response(_who(request))


class LogoutView(OpenView):
    tokenguard_exempt = True

    def post(self, request):
        logout(request)
        return Response({"authenticated": False, "staff": False, "username": None})
