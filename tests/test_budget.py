import uuid
from datetime import datetime, timezone

import pytest

from tokenguard import FakeClock
from tokenguard.budget import (
    Budget,
    BudgetedBucket,
    Cost,
    Spend,
    near_limit_events,
    period_info,
)

START = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc).timestamp()


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def budgeted(redis_client):
    """Factory: budgeted(Budget(...), capacity=..., start=...) -> (bucket, clock)."""
    owners: list[str] = []

    def make(budget, capacity=10_000, rate=1.0, start=START, name=None):
        name = name or f"test-{uuid.uuid4().hex}"
        owners.append(name)
        clock = FakeClock(start)
        bucket = BudgetedBucket(
            redis_client, name, "b", capacity, rate, budget, clock=clock
        )
        return bucket, clock

    yield make
    for name in owners:
        for k in redis_client.scan_iter(f"tb:{{{name}}}:*"):
            redis_client.delete(k)


# ---- pure helpers (no Redis needed) ----
def test_period_info_labels_and_resets():
    p = period_info(utc(2026, 10, 10, 20, 0))
    assert (p.day, p.month) == ("2026-10-10", "2026-10")
    assert p.day_resets_in == pytest.approx(4 * 3600)


def test_period_info_rolls_over_the_year():
    p = period_info(utc(2026, 12, 31, 23, 59, 59))
    assert (p.day, p.month) == ("2026-12-31", "2026-12")
    assert p.day_resets_in == pytest.approx(1)
    assert p.month_resets_in == pytest.approx(1)


def test_cost_burst_is_tokens_times_weight():
    assert Cost(100, dollars=0.5, weight=5).burst == 500


@pytest.mark.parametrize(
    "kwargs", [{"tokens": -1}, {"tokens": 1, "dollars": -1}, {"tokens": 1, "weight": 0}]
)
def test_invalid_costs_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Cost(**kwargs)


def test_invalid_budgets_are_rejected():
    with pytest.raises(ValueError):
        Budget(daily_tokens=-1)
    with pytest.raises(ValueError):
        Budget(near_limit=0)
    with pytest.raises(ValueError):
        Budget(near_limit=1.5)


def test_near_limit_fires_once_when_the_threshold_is_crossed():
    budget = Budget(daily_tokens=1000, near_limit=0.8)
    crossed = near_limit_events(budget, Spend(day_tokens=700), Spend(day_tokens=850))
    assert len(crossed) == 1
    event = crossed[0]
    assert (event["layer"], event["metric"]) == ("daily", "tokens")
    assert event["limit"] == 1000
    assert event["fraction"] == pytest.approx(0.85)
    # already above the threshold, or still below it: nothing new to say
    assert not near_limit_events(budget, Spend(day_tokens=850), Spend(day_tokens=900))
    assert not near_limit_events(budget, Spend(day_tokens=100), Spend(day_tokens=700))


def test_near_limit_ignores_metrics_without_a_cap():
    budget = Budget(daily_tokens=1000)  # no dollar caps
    assert not near_limit_events(budget, Spend(), Spend(day_usd=999.0))


# ---- the atomic multi-layer charge (needs Redis) ----
def test_charges_burst_and_both_budgets_together(budgeted):
    b, _ = budgeted(Budget(daily_tokens=1000, monthly_tokens=5000))
    d = b.charge(Cost(100, dollars=0.5))
    assert d.allowed and d.blocked_by is None
    assert d.remaining == pytest.approx(9_900)
    assert d.spend == Spend(100, 0.5, 100, 0.5)


def test_daily_cap_blocks_even_though_burst_has_tokens(budgeted):
    b, _ = budgeted(Budget(daily_tokens=1000))
    assert b.charge(Cost(600)).allowed
    d = b.charge(Cost(600))
    assert not d.allowed and d.blocked_by == "daily_tokens"
    assert d.remaining == pytest.approx(9_400)  # the burst bucket was NOT charged
    assert d.spend.day_tokens == 600  # neither was the budget: no half-charge
    assert b.charge(Cost(400)).allowed  # exactly what is left still fits


def test_monthly_cap_still_applies_after_the_day_resets(budgeted):
    b, clock = budgeted(Budget(daily_tokens=1000, monthly_tokens=1500))
    assert b.charge(Cost(1000)).allowed
    assert b.charge(Cost(1)).blocked_by == "daily_tokens"
    clock.advance(86_400)  # the next UTC day, same month
    assert b.charge(Cost(500)).allowed  # a fresh daily counter
    assert b.charge(Cost(1)).blocked_by == "monthly_tokens"  # 1,500 used this month


def test_dollar_caps(budgeted):
    b, _ = budgeted(Budget(daily_usd=1.0))
    assert b.charge(Cost(1, dollars=0.6)).allowed
    assert b.charge(Cost(1, dollars=0.6)).blocked_by == "daily_usd"
    assert b.charge(Cost(1, dollars=0.4)).allowed  # 0.6 + 0.4 fits under 1.0


def test_burst_still_limits_when_budgets_have_room(budgeted):
    b, _ = budgeted(Budget(daily_tokens=10**9), capacity=100, rate=1.0)
    assert b.charge(Cost(100)).allowed
    d = b.charge(Cost(10))
    assert d.blocked_by == "burst"
    assert d.retry_after == pytest.approx(10)


def test_a_blocked_request_is_not_charged_to_any_layer(budgeted):
    b, _ = budgeted(Budget(daily_tokens=1000), capacity=100, rate=1.0)
    assert b.charge(Cost(100)).allowed  # empties the burst bucket
    d = b.charge(Cost(50))
    assert d.blocked_by == "burst"
    assert d.spend.day_tokens == 100  # the budget was not charged for the blocked one


def test_daily_retry_after_is_the_time_until_utc_midnight(budgeted):
    b, _ = budgeted(Budget(daily_tokens=100), start=utc(2026, 10, 10, 20, 0))
    b.charge(Cost(100))
    assert b.charge(Cost(1)).retry_after == pytest.approx(4 * 3600)


def test_monthly_retry_after_is_the_time_until_next_month(budgeted):
    b, _ = budgeted(Budget(monthly_tokens=100), start=utc(2026, 10, 31, 23, 0))
    b.charge(Cost(100))
    d = b.charge(Cost(1))
    assert d.blocked_by == "monthly_tokens"
    assert d.retry_after == pytest.approx(3600)


def test_a_request_bigger_than_a_cap_can_never_fit(budgeted):
    b, _ = budgeted(Budget(daily_tokens=1000), capacity=10_000)
    assert b.fits(Cost(1000))
    assert not b.fits(Cost(1001))
    assert not b.fits(Cost(5, weight=5000))  # weighted burst cost 25,000 > capacity


def test_all_keys_share_one_hash_tag(budgeted):
    b, _ = budgeted(Budget(daily_tokens=1), name="alice")
    keys = b.keys(period_info(START))
    assert len(keys) == 3 and all("{alice}" in k for k in keys)


# ---- settling estimates ----
def test_adjust_refunds_burst_and_budgets_together(budgeted):
    b, _ = budgeted(Budget(daily_tokens=5000, daily_usd=1.0))
    d = b.charge(Cost(1000, dollars=0.10))
    remaining, spend = b.adjust(-400, -400, -0.04, d.periods)
    assert remaining == pytest.approx(9_400)
    assert spend.day_tokens == pytest.approx(600)
    assert spend.day_usd == pytest.approx(0.06)
    assert spend.month_tokens == pytest.approx(600)


def test_adjust_books_to_the_period_the_charge_was_made_in(budgeted):
    start = utc(2026, 10, 10, 23, 59, 50)
    b, clock = budgeted(Budget(daily_tokens=5000), start=start)
    d = b.charge(Cost(1000))
    clock.advance(20)  # it is now Oct 11
    _, spend = b.adjust(-400, -400, 0.0, d.periods)
    assert spend.day_tokens == pytest.approx(600)  # Oct 10's counter was refunded
    assert b.charge(Cost(5000)).allowed  # Oct 11 is untouched: the full 5,000 is there


def test_adjust_never_drives_spend_below_zero(budgeted):
    b, _ = budgeted(Budget(daily_tokens=5000))
    d = b.charge(Cost(10))
    _, spend = b.adjust(-10_000, -10_000, -5.0, d.periods)
    assert (spend.day_tokens, spend.day_usd) == (0.0, 0.0)


def test_overspend_is_recorded_and_blocks_the_next_request(budgeted):
    b, _ = budgeted(Budget(daily_tokens=1000))
    d = b.charge(Cost(900))
    _, spend = b.adjust(500, 500, 0.0, d.periods)  # really used 500 more
    assert spend.day_tokens == pytest.approx(1400)
    assert b.charge(Cost(1)).blocked_by == "daily_tokens"
