import pytest

from tokenguard import llm


def test_heuristic_is_about_four_chars_per_token():
    assert llm.estimate_tokens("abcd") == 1
    assert llm.estimate_tokens("abcde") == 2  # rounds up
    assert llm.estimate_tokens("") == 0


def test_estimator_is_pluggable_per_call():
    assert llm.estimate_tokens("hello", estimator=lambda text, model: 99) == 99


def test_estimator_receives_the_model_name():
    seen = []
    llm.estimate_tokens("hi", "large", estimator=lambda t, m: seen.append(m) or 1)
    assert seen == ["large"]


def test_set_estimator_changes_the_default():
    try:
        llm.set_estimator(lambda text, model: 7)
        assert llm.estimate_tokens("anything") == 7
    finally:
        llm.set_estimator(llm.heuristic_estimator)
    assert llm.estimate_tokens("abcd") == 1


def test_negative_estimates_are_clamped_to_zero():
    assert llm.estimate_tokens("x", estimator=lambda t, m: -5) == 0


def test_default_and_unknown_models():
    assert llm.get_model().name == llm.DEFAULT_MODEL
    with pytest.raises(ValueError, match="unknown model"):
        llm.get_model("gpt-banana")


def test_request_cost_is_input_plus_expected_output():
    # 400 chars = 100 input tokens; small model assumes 256 output by default
    assert llm.estimate_request_cost("x" * 400, "small") == 100 + 256
    # the large model assumes 512 by default
    assert llm.estimate_request_cost("x" * 400, "large") == 100 + 512


def test_explicit_max_output_tokens_is_used():
    assert llm.estimate_request_cost("x" * 400, "small", max_output_tokens=50) == 150
    assert llm.estimate_request_cost("x" * 400, "small", max_output_tokens=0) == 100


def test_output_is_capped_at_the_models_own_limit():
    spec = llm.get_model("small")
    cost = llm.estimate_request_cost("", "small", max_output_tokens=10**9)
    assert cost == spec.max_output_tokens


def test_50_token_and_50000_token_requests_are_very_different():
    small = llm.estimate_request_cost("x" * 200, "small", max_output_tokens=0)
    huge = llm.estimate_request_cost("x" * 200_000, "large", max_output_tokens=0)
    assert (small, huge) == (50, 50_000)


def test_dollar_cost_uses_the_price_table():
    # small: $0.15 per 1M input tokens, $0.60 per 1M output tokens
    assert llm.dollar_cost("small", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert llm.dollar_cost("large", 1000, 0) == pytest.approx(0.003)


def test_register_model_adds_to_the_table():
    spec = llm.ModelSpec("tiny", 1000, 100, 10, 0.1, 0.2)
    try:
        llm.register_model(spec)
        assert llm.get_model("tiny") is spec
    finally:
        llm.MODELS.pop("tiny", None)


def test_expensive_models_are_weighted_more_heavily():
    assert llm.get_model("small").weight == 1
    assert llm.get_model("large").weight == 5


def test_estimate_request_splits_input_and_output():
    est = llm.estimate_request("x" * 400, "small", max_output_tokens=50)
    assert (est.input_tokens, est.output_tokens, est.tokens) == (100, 50, 150)


def test_estimate_request_cost_is_the_total_tokens():
    assert llm.estimate_request_cost("x" * 400, "small", 50) == 150
