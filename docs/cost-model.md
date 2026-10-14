# Cost model (Week 4)

## Estimating a request
`cost = input_tokens + expected_output_tokens`, where input is estimated at
~4 characters per token (pluggable, e.g. tiktoken) and output is `max_tokens`
(or the model default). Every request is charged **up front** (estimate), then
**reconciled** with the provider's real usage when the response arrives.

## Model weights
Each model has a `weight` (small = 1.0, large = 5.0). The burst-bucket charge is
`tokens * weight`, so one large-model token costs five small-model tokens.
Buckets are per `(user, model)`: heavy use of the large model empties only the
large bucket and never blocks the small one. A request whose weighted cost can
never fit the bucket capacity gets **413**, not 429.

## Reconciliation
- Actual < estimate: the difference is refunded (capped at capacity).
- Actual > estimate: the extra is charged; the bucket may go into bounded debt
  (floor `-capacity`).
- 5xx / exception: full refund. 4xx stays charged.

## Budgets and dollars
A `Budget(daily_tokens, daily_usd, monthly_tokens, monthly_usd)` sits **on top**
of the burst bucket, per owner (`budget_key`, usually the user, shared across
models). Periods are UTC days and months.

One Lua call (`token_bucket_budget.lua`) checks monthly tokens, monthly USD,
daily tokens, daily USD and the burst bucket, then charges **all or nothing**.
So exceeding the daily cap blocks the request even when the burst bucket still
has tokens, and a blocked request is never partially charged. Keys share the
hash tag `{budget_id}` so they live in one Redis Cluster slot.

Settlement (`token_bucket_budget_adjust.lua`) applies refunds/extra charges to
the burst bucket and to the day/month counters captured at charge time (so a
refund after midnight lands on the right day). Spend counters never go below 0.

Budget blocks return 429 `budget_exceeded` with the `limit` that tripped and a
`Retry-After` pointing at the next UTC midnight / month start.

## Near-limit alerts
After settlement, `finalize()` compares spend before/after against each limit
and fires `ON_NEAR_LIMIT(event)` (callable or dotted path) once when a limit
crosses the threshold, using final numbers, so estimate overshoot that gets
refunded never triggers a false alarm. A warning is also logged.

## Reconciliation edge cases

| Situation | What happens |
|---|---|
| Actual usage above the estimate | The extra is charged. The burst bucket may go into debt, but never below `-capacity`, so one huge reply cannot lock a user out for hours. Budget counters record the full real usage. |
| Actual usage below the estimate | The difference is refunded, capped at `capacity`. |
| Zero usage reported | Everything is refunded: burst tokens, budget tokens and (when the response reports prompt and completion counts) dollars. |
| Only `total_tokens` reported | Tokens are settled, but the dollar *estimate* is kept, because the input/output split is unknown. |
| Usage missing or unreadable | The estimate stands. |
| View raises, or returns a 5xx | Full refund (burst bucket, daily and monthly counters). Our upstream's failure is not the caller's fault. |
| View returns a 4xx | Stays charged. Otherwise flooding the API with invalid requests would be free. |
| Settled twice | Only the first settlement counts. |
| Redis down while settling | The response is still returned; the failure is logged. |

These are all tested in `tests/test_reconcile_edges.py`.

## Streaming responses (known limitation)

With a streamed reply the usage numbers arrive in the last chunk, after the
response has already started. The decorator settles when the view returns, so
for a streaming response it can only keep the up-front estimate. Today you can:

- call `request.tokenguard.reconcile(usage)` yourself when the stream ends, or
- charge a pessimistic estimate (`max_tokens`) and accept the over-charge.

Settling automatically at the end of a stream (wrapping the response iterator)
is planned future work.
