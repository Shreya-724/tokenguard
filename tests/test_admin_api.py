"""The logic behind the staff REST API (no web framework needed to test it)."""

import time
import uuid

import pytest

pytest.importorskip("django")

from tokenguard.budget import Budget  # noqa: E402
from tokenguard.django import admin_api, catalog  # noqa: E402
from tokenguard.django.admin_api import ApiError  # noqa: E402
from tokenguard.django.engine import Rule  # noqa: E402


def config(url, prefix, **extra):
    cfg = {
        "REDIS_URL": url,
        "KEY_PREFIX": prefix,
        "DEFAULT_RULE": {"capacity": 3, "refill_rate": 0.001},
        "EXEMPT": [r"^/health/"],
        "RULES": [
            {
                "name": "login",
                "match": r"^/login/",
                "capacity": 2,
                "refill_rate": 0.001,
                "key": "ip",
            }
        ],
        "METRICS": True,
        "LIVE_RULES": True,
        "LIVE_RULES_TTL": 60,
    }
    cfg.update(extra)
    return cfg


@pytest.fixture
def prefix(redis_client):
    p = f"tgapi-{uuid.uuid4().hex[:8]}"
    yield p
    for k in redis_client.scan_iter(f"{p}:*"):
        redis_client.delete(k)


@pytest.fixture
def on(settings, redis_url, prefix):
    settings.TOKENGUARD = config(redis_url, prefix)


@pytest.fixture
def extra_rules():
    """Register rules like @rate_limit does, and remove them afterwards."""
    added = []

    def add(scope, **kwargs):
        rule = Rule(10, 1, lambda r: "k", scope=scope, **kwargs)
        catalog.register_rule(rule)
        added.append(scope)
        return rule

    yield add
    for scope in added:
        catalog._VIEW_RULES.pop(scope, None)


def by_scope(listing):
    return {r["scope"]: r for r in listing["rules"]}


# ---- the rule catalog ----
def test_settings_and_view_rules_are_all_known(on, extra_rules):
    extra_rules("myapp.views.search")
    known = catalog.known_rules()
    assert known["default"][0] == "default"
    assert known["login"][0] == "settings"
    assert known["myapp.views.search"][0] == "view"


def test_a_decorated_view_registers_itself():
    from demo_site import views  # noqa: F401  (importing it runs the decorators)

    assert any(source == "view" for source, _ in catalog.known_rules().values())


# ---- listing rules ----
def test_list_rules_shows_configured_and_effective(on):
    listing = admin_api.list_rules()
    rules = by_scope(listing)
    assert listing["live_rules_enabled"] is True
    assert rules["default"]["configured"] == {
        "capacity": 3,
        "refill_rate": 0.001,
        "algorithm": "token_bucket",
    }
    assert rules["default"]["effective"] == rules["default"]["configured"]
    assert rules["default"]["override"] is None
    assert rules["login"]["source"] == "settings"


# ---- changing a rule live ----
def test_updating_a_rule_changes_what_is_effective(on):
    before = admin_api.list_rules()["version"]
    new = {"capacity": 50, "algorithm": "fixed_window"}
    out = admin_api.update_rule("default", new)
    assert out["override"] == {
        "capacity": 50,
        "refill_rate": None,
        "algorithm": "fixed_window",
    }
    assert out["effective"] == {
        "capacity": 50,
        "refill_rate": 0.001,
        "algorithm": "fixed_window",
    }
    assert out["configured"]["capacity"] == 3  # the settings are untouched
    assert admin_api.list_rules()["version"] > before


def test_a_change_takes_hold_on_real_traffic(on, client):
    assert [client.get("/api/ping/").status_code for _ in range(4)] == [
        200,
        200,
        200,
        429,
    ]
    admin_api.update_rule("default", {"capacity": 1000, "refill_rate": 1000})
    time.sleep(0.05)  # 50 ms at 1000 tokens/second refills the empty bucket
    response = client.get("/api/ping/")
    assert response.status_code == 200
    assert response["X-RateLimit-Limit"] == "1000"


def test_reset_puts_the_rule_back(on):
    admin_api.update_rule("login", {"capacity": 99})
    out = admin_api.reset_rule("login")
    assert out["override"] is None
    assert out["effective"]["capacity"] == 2


def test_overrides_are_shown_but_not_applied_when_live_rules_is_off(
    settings, redis_url, prefix
):
    settings.TOKENGUARD = config(redis_url, prefix, LIVE_RULES=False)
    out = admin_api.update_rule("default", {"capacity": 50})
    listing = admin_api.list_rules()
    assert listing["live_rules_enabled"] is False
    assert out["override"]["capacity"] == 50
    assert out["effective"]["capacity"] == 3  # not live: still the settings


@pytest.mark.parametrize(
    "data",
    [
        {"capacity": -1},
        {"capacity": 0},
        {"capacity": "lots"},
        {"refill_rate": float("inf")},
        {"algorithm": "leaky_bucket"},
        {"colour": "red"},
        {},
        [],
        "capacity=5",
    ],
)
def test_bad_updates_are_refused_with_400(on, data):
    with pytest.raises(ApiError) as caught:
        admin_api.update_rule("default", data)
    assert caught.value.status == 400
    assert admin_api.list_rules()["version"] == 0  # nothing was written


def test_a_budgeted_rule_cannot_take_a_window_algorithm(on, extra_rules):
    extra_rules("llm.chat", budget=Budget(daily_tokens=1000))
    with pytest.raises(ApiError) as caught:
        admin_api.update_rule("llm.chat", {"algorithm": "fixed_window"})
    assert caught.value.status == 400
    assert (
        admin_api.update_rule("llm.chat", {"capacity": 20})["effective"]["capacity"]
        == 20
    )


def test_unknown_rules_are_404(on):
    for call in (
        lambda: admin_api.update_rule("nope", {"capacity": 5}),
        lambda: admin_api.reset_rule("nope"),
        lambda: admin_api.get_rule("nope"),
    ):
        with pytest.raises(ApiError) as caught:
            call()
        assert caught.value.status == 404


# ---- stats and consumers ----
def test_stats_count_real_requests(on, client):
    for _ in range(5):
        client.get("/api/ping/")
    snap = admin_api.stats(seconds=30)
    assert snap["summary"]["allowed"] == 3 and snap["summary"]["blocked"] == 2
    assert len(snap["series"]) == 30
    assert snap["routes"][0]["scope"] == "default"


def test_consumers_lists_the_caller(on, client):
    for _ in range(5):
        client.get("/api/ping/")
    out = admin_api.consumers()
    assert out["by"] == "tokens"
    assert out["consumers"][0]["scope"] == "default"
    assert admin_api.consumers(by="blocked")["consumers"][0]["blocked"] == 2


def test_bad_query_values_are_400(on):
    for call in (
        lambda: admin_api.stats(seconds=0),
        lambda: admin_api.stats(step=0),
        lambda: admin_api.consumers(by="requests"),
        lambda: admin_api.consumers(n=5, minutes=0),
    ):
        with pytest.raises(ApiError) as caught:
            call()
        assert caught.value.status == 400


# ---- one bucket ----
def test_bucket_shows_what_a_caller_has_left(on, client):
    for _ in range(2):
        client.get("/api/ping/")
    out = admin_api.bucket("default:ip:127.0.0.1")
    assert out["scope"] == "default" and out["identity"] == "ip:127.0.0.1"
    assert out["capacity"] == 3
    assert out["remaining"] == pytest.approx(1, abs=0.1)


def test_looking_at_a_bucket_does_not_spend_it(on, client):
    client.get("/api/ping/")
    first = admin_api.bucket("default:ip:127.0.0.1")["remaining"]
    for _ in range(5):
        admin_api.bucket("default:ip:127.0.0.1")
    assert admin_api.bucket("default:ip:127.0.0.1")["remaining"] == pytest.approx(
        first, abs=0.1
    )


def test_bucket_uses_the_live_limit(on):
    admin_api.update_rule("default", {"capacity": 40})
    assert admin_api.bucket("default:ip:1.2.3.4")["capacity"] == 40


def test_the_most_specific_scope_wins(on, extra_rules):
    extra_rules("api")
    extra_rules("api:v2")
    assert admin_api.bucket("api:v2:user:7")["scope"] == "api:v2"
    assert admin_api.bucket("api:user:7")["scope"] == "api"


@pytest.mark.parametrize("key", ["nosuchscope:ip:1", "default:", "default", ""])
def test_bucket_rejects_keys_that_match_no_rule(on, key):
    with pytest.raises(ApiError) as caught:
        admin_api.bucket(key)
    assert caught.value.status == 404


def test_bucket_of_a_budgeted_rule_is_not_available(on, extra_rules):
    extra_rules("llm.chat", budget=Budget(daily_tokens=1000))
    with pytest.raises(ApiError) as caught:
        admin_api.bucket("llm.chat:user:1")
    assert caught.value.status == 422


# ---- Redis down ----
def test_everything_says_503_when_redis_is_down(settings, redis_url, prefix):
    settings.TOKENGUARD = config(
        redis_url, prefix, REDIS_URL="redis://localhost:6399/0", REDIS_TIMEOUT=0.2
    )
    for call in (
        lambda: admin_api.stats(),
        lambda: admin_api.consumers(),
        lambda: admin_api.bucket("default:ip:1"),
    ):
        with pytest.raises(ApiError) as caught:
            call()
        assert caught.value.status == 503
