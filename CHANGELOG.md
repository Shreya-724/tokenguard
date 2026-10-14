# Changelog

## 0.3.0

Token-aware limiting for LLM APIs.

- Cost model: `estimate_tokens(text, model)`, a model table with limits, prices and
  weights, a pluggable estimator (heuristic by default, tiktoken optional).
- `cost=callable(request)` on the decorator and middleware rules; requests that can
  never fit are rejected with 413 instead of 429.
- Reconciliation: atomic `adjust` Lua script refunds or charges the difference
  between estimate and real usage. Debt is bounded at one bucket.
- Per-(user, model) buckets with cost weights (the large model counts 5x).
- Budgets: burst, daily and monthly limits in tokens and dollars, checked and
  charged in one atomic Lua call. Near-limit alert hook (`ON_NEAR_LIMIT`).
- Mock chat endpoint (`/api/llm/chat/`) and a 2-minute demo (`scripts/demo_llm.py`).
- Known limitation: streaming responses (see docs/cost-model.md).

## 0.2.0

Django integration: decorator, middleware, headers, fail-open/closed modes.

## 0.1.0

Token bucket, Redis backend with atomic Lua script.
