"""Cost model for LLM requests: how many tokens (and dollars) a request is worth.

A normal rate limiter charges 1 per request. For an LLM API that is wrong: a
50-token prompt and a 50,000-token prompt cost wildly different amounts. Here a
request's cost is its estimated tokens: input tokens plus the output we expect.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

# (text, model name or None) -> estimated token count
Estimator = Callable[[str, "str | None"], int]


@dataclass(frozen=True)
class ModelSpec:
    name: str
    context_window: int  # max input + output tokens the model accepts
    max_output_tokens: int  # the most it can generate in one reply
    default_output_tokens: int  # assumed output when the caller doesn't say
    input_price_per_mtok: float  # dollars per 1,000,000 input tokens
    output_price_per_mtok: float  # dollars per 1,000,000 output tokens
    weight: float = 1.0  # burst-bucket multiplier: 5.0 means every token counts 5x


# ILLUSTRATIVE numbers. Replace them with your provider's real limits and prices.
MODELS: dict[str, ModelSpec] = {
    "small": ModelSpec("small", 16_000, 2_000, 256, 0.15, 0.60, weight=1.0),
    "large": ModelSpec("large", 128_000, 8_000, 512, 3.00, 15.00, weight=5.0),
}
DEFAULT_MODEL = "small"


def register_model(spec: ModelSpec) -> None:
    """Add or replace a model in the table."""
    MODELS[spec.name] = spec


def get_model(name: str | None = None) -> ModelSpec:
    """Look a model up by name (None means the default model)."""
    key = DEFAULT_MODEL if name is None else name
    try:
        return MODELS[key]
    except KeyError:
        known = ", ".join(sorted(MODELS))
        raise ValueError(f"unknown model {key!r}; known models: {known}") from None


def heuristic_estimator(text: str, model: str | None = None) -> int:
    """About 4 characters per token (rounded up). Cheap, and good enough to start."""
    return math.ceil(len(text) / 4) if text else 0


_estimator: Estimator = heuristic_estimator


def set_estimator(estimator: Estimator) -> None:
    """Replace the default estimator, for example with tiktoken_estimator()."""
    global _estimator
    _estimator = estimator


def tiktoken_estimator(encoding_name: str = "cl100k_base") -> Estimator:
    """Estimator backed by tiktoken (pip install tiktoken).

    It is OpenAI's tokenizer, so for other providers it is an approximation, and
    it downloads its vocabulary the first time it is used.
    """
    import tiktoken

    encoding = tiktoken.get_encoding(encoding_name)

    def estimate(text: str, model: str | None = None) -> int:
        return len(encoding.encode(text))

    return estimate


def estimate_tokens(
    text: str, model: str | None = None, estimator: Estimator | None = None
) -> int:
    """Estimate how many tokens `text` is. Never negative."""
    fn = estimator or _estimator
    return max(0, int(fn(text, model)))


@dataclass(frozen=True)
class RequestEstimate:
    input_tokens: int
    output_tokens: int

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def estimate_request(
    prompt: str,
    model: str | None = None,
    max_output_tokens: int | None = None,
    estimator: Estimator | None = None,
) -> RequestEstimate:
    """Estimated input and expected output tokens for one request.

    The output length is unknown until the model answers, so we charge for what
    the caller allows (max_output_tokens, capped at the model's own limit), or
    the model's default. Reconciliation refunds the unused part afterwards.
    """
    spec = get_model(model)
    input_tokens = estimate_tokens(prompt, spec.name, estimator)
    if max_output_tokens is None:
        max_output_tokens = spec.default_output_tokens
    output = max(0, min(max_output_tokens, spec.max_output_tokens))
    return RequestEstimate(input_tokens, output)


def estimate_request_cost(
    prompt: str,
    model: str | None = None,
    max_output_tokens: int | None = None,
    estimator: Estimator | None = None,
) -> int:
    """Tokens to charge up front: estimated input + expected output."""
    return estimate_request(prompt, model, max_output_tokens, estimator).tokens


def dollar_cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """Dollars for a finished request, from the price table."""
    spec = get_model(model)
    return (
        input_tokens * spec.input_price_per_mtok
        + output_tokens * spec.output_price_per_mtok
    ) / 1_000_000
