"""Ready-made cost and usage functions for LLM-style JSON endpoints.

    @rate_limit(capacity=10_000, refill_rate=50, cost=llm_cost(), usage=llm_usage())
    def complete(request): ...

llm_cost reads the request body BEFORE the view runs and estimates its tokens.
llm_usage reads the response AFTER the view runs so the estimate can be settled
against what the model really used.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from tokenguard.llm import DEFAULT_MODEL, MODELS, Estimator, estimate_request_cost


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
) -> Callable[[Any], float]:
    """Build a cost function: request -> estimated tokens (input + expected output)."""

    def cost(request) -> float:
        try:
            body = json.loads(request.body or b"{}")
        except ValueError:
            return 1.0  # not our job to reject bad JSON; the view answers 400
        if not isinstance(body, dict):
            return 1.0
        model = body.get(model_field)
        if model not in MODELS:
            model = DEFAULT_MODEL  # the view should reject unknown models itself
        max_tokens = body.get(max_tokens_field)
        if (
            not isinstance(max_tokens, int)
            or isinstance(max_tokens, bool)
            or max_tokens < 0
        ):
            max_tokens = None
        prompt = _prompt_text(body.get(prompt_field))
        return float(estimate_request_cost(prompt, model, max_tokens, estimator))

    return cost


def llm_usage(usage_field: str = "usage") -> Callable[[Any, Any], float | None]:
    """Build a usage function: (request, response) -> tokens really used, or None.

    Understands {"usage": {"total_tokens": n}} and
    {"usage": {"prompt_tokens": a, "completion_tokens": b}}. Returning None
    keeps the estimate as the final charge.
    """

    def usage(request, response) -> float | None:
        try:
            data = getattr(response, "data", None)  # DRF Response
            if data is None:
                data = json.loads(response.content)
            used = data[usage_field]
            if "total_tokens" in used:
                return float(used["total_tokens"])
            return float(used["prompt_tokens"]) + float(used["completion_tokens"])
        except Exception:
            return None

    return usage
