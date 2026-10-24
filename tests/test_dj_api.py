"""The staff-only REST endpoints, through Django REST Framework."""

import uuid

import pytest

pytest.importorskip("django")
pytest.importorskip("rest_framework.test")

from django.contrib.auth.models import User  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

PATHS = [
    ("get", "/tokenguard/stats/"),
    ("get", "/tokenguard/consumers/"),
    ("get", "/tokenguard/buckets/default:ip:1.2.3.4/"),
    ("get", "/tokenguard/rules/"),
    ("get", "/tokenguard/rules/default/"),
    ("put", "/tokenguard/rules/default/"),
    ("delete", "/tokenguard/rules/default/"),
]


@pytest.fixture
def on(settings, redis_client, redis_url):
    prefix = f"tgdrf-{uuid.uuid4().hex[:8]}"
    settings.TOKENGUARD = {
        "REDIS_URL": redis_url,
        "KEY_PREFIX": prefix,
        "DEFAULT_RULE": {"capacity": 1, "refill_rate": 0.001},  # tiny on purpose
        "METRICS": True,
        "LIVE_RULES": True,
        "LIVE_RULES_TTL": 60,
    }
    yield
    for k in redis_client.scan_iter(f"{prefix}:*"):
        redis_client.delete(k)


def as_user(**fields):
    client = APIClient()
    client.force_authenticate(User(username="someone", **fields))  # no DB needed
    return client


@pytest.fixture
def staff(on):
    return as_user(is_staff=True)


# ---- who gets in ----
@pytest.mark.parametrize("method,url", PATHS)
def test_anonymous_callers_are_refused(on, method, url):
    response = getattr(APIClient(), method)(url, {}, format="json")
    assert response.status_code in (401, 403)


@pytest.mark.parametrize("method,url", PATHS)
def test_signed_in_non_staff_are_refused(on, method, url):
    response = getattr(as_user(is_staff=False), method)(url, {}, format="json")
    assert response.status_code == 403


def test_nothing_leaks_in_a_refusal(on):
    body = APIClient().get("/tokenguard/rules/").content.decode()
    assert "capacity" not in body


# ---- the endpoints ----
def test_stats(staff):
    response = staff.get("/tokenguard/stats/?seconds=20")
    assert response.status_code == 200
    data = response.json()
    assert len(data["series"]) == 20 and "summary" in data


def test_stats_counts_traffic(staff):
    for _ in range(3):
        APIClient().get("/api/ping/")  # 1 allowed, 2 blocked (capacity 1)
    data = staff.get("/tokenguard/stats/").json()
    assert (data["summary"]["allowed"], data["summary"]["blocked"]) == (1, 2)


def test_consumers(staff):
    for _ in range(3):
        APIClient().get("/api/ping/")
    data = staff.get("/tokenguard/consumers/?by=blocked&n=3").json()
    assert data["by"] == "blocked" and data["consumers"][0]["blocked"] == 2


def test_bucket_with_colons_in_the_key(staff):
    response = staff.get("/tokenguard/buckets/default:ip:127.0.0.1/")
    assert response.status_code == 200
    assert response.json()["identity"] == "ip:127.0.0.1"


def test_rule_list_and_update_and_reset(staff):
    listing = staff.get("/tokenguard/rules/").json()
    assert listing["live_rules_enabled"] is True
    assert any(r["scope"] == "default" for r in listing["rules"])

    put = staff.put("/tokenguard/rules/default/", {"capacity": 25}, format="json")
    assert put.status_code == 200
    assert put.json()["effective"]["capacity"] == 25
    assert staff.get("/tokenguard/rules/default/").json()["override"]["capacity"] == 25

    gone = staff.delete("/tokenguard/rules/default/")
    assert gone.status_code == 200 and gone.json()["override"] is None


def test_a_rule_name_with_dots_works(staff):
    from demo_site import views  # noqa: F401  (registers the decorated views)

    scope = next(s for s in _scopes(staff) if s.startswith("demo_site.views."))
    assert staff.get(f"/tokenguard/rules/{scope}/").status_code == 200


def _scopes(client):
    return [r["scope"] for r in client.get("/tokenguard/rules/").json()["rules"]]


# ---- errors are JSON with the right status ----
def test_bad_input_is_400_with_a_message(staff):
    r = staff.put("/tokenguard/rules/default/", {"capacity": -5}, format="json")
    assert r.status_code == 400 and "capacity" in r.json()["error"]
    assert staff.get("/tokenguard/stats/?seconds=abc").status_code == 400
    assert staff.get("/tokenguard/stats/?seconds=0").status_code == 400
    assert staff.get("/tokenguard/consumers/?by=cats").status_code == 400


def test_unknown_things_are_404(staff):
    assert staff.get("/tokenguard/rules/nope/").status_code == 404
    bad = staff.put("/tokenguard/rules/nope/", {"capacity": 5}, format="json")
    assert bad.status_code == 404
    assert staff.get("/tokenguard/buckets/nope:ip:1/").status_code == 404


def test_wrong_methods_are_405(staff):
    assert staff.post("/tokenguard/stats/", {}, format="json").status_code == 405
    assert staff.delete("/tokenguard/rules/").status_code == 405


# ---- the admin API never eats the limiter's budget ----
def test_the_endpoints_are_exempt_from_rate_limiting(staff):
    codes = {staff.get("/tokenguard/stats/").status_code for _ in range(5)}
    assert codes == {200}  # DEFAULT_RULE allows one request in total


# ---- signing in (the dashboard's login) ----
@pytest.fixture
def people(db):
    User.objects.create_user("boss", "boss@example.com", "correct-horse", is_staff=True)
    User.objects.create_user("intern", "i@example.com", "hunter2", is_staff=False)


def test_session_reports_anonymous_and_sets_the_csrf_cookie(on):
    client = APIClient()
    data = client.get("/tokenguard/session/").json()
    assert data == {"authenticated": False, "staff": False, "username": None}
    assert "csrftoken" in client.cookies


@pytest.mark.django_db
def test_a_staff_user_can_sign_in_and_use_the_api(on, people):
    client = APIClient()
    assert client.get("/tokenguard/stats/").status_code in (401, 403)
    r = client.post(
        "/tokenguard/login/",
        {"username": "boss", "password": "correct-horse"},
        format="json",
    )
    assert r.status_code == 200 and r.json()["staff"] is True
    assert client.get("/tokenguard/stats/").status_code == 200  # the session works
    assert client.get("/tokenguard/session/").json()["username"] == "boss"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "username,password",
    [("boss", "wrong"), ("nobody", "x"), ("intern", "hunter2")],  # not staff
)
def test_bad_credentials_and_non_staff_get_the_same_401(on, people, username, password):
    r = APIClient().post(
        "/tokenguard/login/",
        {"username": username, "password": password},
        format="json",
    )
    assert r.status_code == 401
    assert r.json() == {"error": "invalid credentials, or not a staff account"}


def test_login_needs_both_fields(on):
    r = APIClient().post("/tokenguard/login/", {"username": "boss"}, format="json")
    assert r.status_code == 400


@pytest.mark.django_db
def test_logout_ends_the_session(on, people):
    client = APIClient()
    client.post(
        "/tokenguard/login/",
        {"username": "boss", "password": "correct-horse"},
        format="json",
    )
    assert client.post("/tokenguard/logout/", {}, format="json").status_code == 200
    assert client.get("/tokenguard/stats/").status_code in (401, 403)


@pytest.mark.django_db
def test_login_and_logout_are_protected_against_csrf(on, people, settings):
    # `on` allows ONE request in total (to prove the API is exempt). Login is not
    # exempt, so give this test enough room for its three login attempts.
    settings.TOKENGUARD = {
        **settings.TOKENGUARD,
        "DEFAULT_RULE": {"capacity": 50, "refill_rate": 1},
    }
    client = APIClient(enforce_csrf_checks=True)
    body = {"username": "boss", "password": "correct-horse"}
    assert client.post("/tokenguard/login/", body, format="json").status_code == 403
    client.get("/tokenguard/session/")  # hands out the CSRF cookie
    token = client.cookies["csrftoken"].value
    ok = client.post(
        "/tokenguard/login/", body, format="json", HTTP_X_CSRFTOKEN=token
    )
    assert ok.status_code == 200


@pytest.mark.django_db
def test_changing_a_rule_over_a_session_needs_the_csrf_token(on, people):
    client = APIClient(enforce_csrf_checks=True)
    client.get("/tokenguard/session/")
    token = client.cookies["csrftoken"].value
    client.post(
        "/tokenguard/login/",
        {"username": "boss", "password": "correct-horse"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    token = client.cookies["csrftoken"].value  # may have been rotated
    url = "/tokenguard/rules/default/"
    assert client.put(url, {"capacity": 9}, format="json").status_code == 403
    ok = client.put(url, {"capacity": 9}, format="json", HTTP_X_CSRFTOKEN=token)
    assert ok.status_code == 200
