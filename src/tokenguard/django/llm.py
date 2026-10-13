"""Ready-made cost, usage and key functions for LLM-style JSON endpoints.

    @rate_limit(
        capacity=10_000,
        refill_rate=50,
        key=user_model,          # a separate burst bucket per (user, model)
        cost=llm_cost(),         # estimated tokens + dollars + the model's weight
        usage=llm_usage(),       # real usage, to settle the estimate afterwards
    )
    def complete(request): ...

llm_cost reads the request body BEFORE the view runs and estimates its cost.
llm_usage reads the response AFTER the view runs so the estimate can be settled
against what the model really used.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from tokenguard.budget import Cost, Usage
from tokenguard.django.keys import KeyFunc, combine, user
from tokenguard.llm import (
    DEFAULT_MODEL,
    MODELS,
    Estimator,
    dollar_cost,
    estimate_request,
    get_model,
)


def _body(request) -> dict[str, Any]:
    """The JSON body as a dict, or {} if it is missing or not a JSON object."""
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _model_name(body: dict[str, Any], model_field: str) -> str:
    """The requested model, or the default if it is missing or unknown.

    Unknown names are NOT used as keys: otherwise a client could invent a new
    model name per request and get a fresh bucket every time. The view should
    reject unknown models itself.
    """
    model = body.get(model_field)
    return model if isinstance(model, str) and model in MODELS else DEFAULT_MODEL


def _prompt_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):  # chat format: [{"role": "user", "content": "hi"}]
        return "\n".join(
            str(m.get("content", "")) if isinstance(m, dict) else str(m) for m in value
        )
    return ""


def llm_cost(
    prompt_field: str = "prompt",
    model_field: str = "model",
    max_tokens_field: str = "max_tokens",
    estimator: Estimator | None = None,
) -> Callable[[Any], Cost]:
    """Build a cost function: request -> Cost(tokens, dollars, model weight)."""

    def cost(request) -> Cost:
        body = _body(request)
        if not body:
            return Cost(1.0)  # not our job to reject bad JSON; the view answers 400
        model = _model_name(body, model_field)
        max_tokens = body.get(max_tokens_field)
        if (
            not isinstance(max_tokens, int)
            or isinstance(max_tokens, bool)
            or max_tokens < 0
        ):
            max_tokens = None
        estimate = estimate_request(
            _prompt_text(body.get(prompt_field)), model, max_tokens, estimator
        )
        return Cost(
            tokens=estimate.tokens,
            dollars=dollar_cost(model, estimate.input_tokens, estimate.output_tokens),
            weight=get_model(model).weight,
        )

    return cost


def llm_usage(
    usage_field: str = "usage", model_field: str = "model"
) -> Callable[[Any, Any], Usage | None]:
    """Build a usage function: (request, response) -> Usage, or None if unknown.

    Understands {"usage": {"prompt_tokens": a, "completion_tokens": b}}, which
    also gives exact dollars, and {"usage": {"total_tokens": n}}, which does not
    (the dollar estimate is kept). Returning None keeps the estimate.
    """

    def usage(request, response) -> Usage | None:
        try:
            data = getattr(response, "data", None)  # DRF Response
            if data is None:
                data = json.loads(response.content)
            used = data[usage_field]
            if "prompt_tokens" in used and "completion_tokens" in used:
                prompt = float(used["prompt_tokens"])
                completion = float(used["completion_tokens"])
                model = _model_name(_body(request), model_field)
                dollars = dollar_cost(model, prompt, completion)
                return Usage(prompt + completion, dollars)
            return Usage(float(used["total_tokens"]))
        except Exception:
            return None

    return usage


def model_key(model_field: str = "model") -> KeyFunc:
    """Key function: "model:small". Combine it with a user key for per-model buckets."""

    def key(request) -> str:
        return f"model:{_model_name(_body(request), model_field)}"

    return key


# One burst bucket per (user, model). Expensive models get their own bucket, so
# heavy use of the large model never blocks the small one.
user_model = combine(user, model_key())
