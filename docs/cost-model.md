# Cost model: charging LLM requests by tokens

## The problem
A classic rate limiter charges 1 per request. For an LLM API that is meaningless: a
50-token prompt and a 50,000-token prompt both cost "1", yet the second costs a
thousand times more to serve (and to pay for). tokenguard charges **tokens**.

## What a request costs
```
cost = estimated input tokens + expected output tokens
```
- **Input** is known up front, so it is estimated from the prompt text.
- **Output** is unknown until the model answers. We charge for what the caller
  allows (`max_tokens`, capped at the model's own output limit), or the model's
  default. This is deliberately pessimistic.
- After the call, **reconciliation** settles the difference (see below).

## Estimating tokens
`estimate_tokens(text, model)` uses a pluggable estimator. The default is a
heuristic of about 4 characters per token, which is cheap and needs no
dependencies. For a closer count, plug in `tiktoken_estimator()`. It is OpenAI's
tokenizer, so it is only an approximation for other providers, and an estimate
is all we need: the real numbers arrive in the response.

## Model table
Each model has a context window, an output cap, a default output length, and
prices per million input and output tokens (`tokenguard.llm.MODELS`). The prices
in the repository are illustrative; put your provider's real ones in.

## Reconciliation: estimate first, settle after
1. **Before** the call: charge the estimate. If the bucket cannot cover it, the
   request is rejected and the model is never called.
2. **After** the call: read the real usage from the response and settle:
   - used less than estimated -> the difference is **refunded** (capped at capacity)
   - used more than estimated -> the extra is **charged**
   - the call failed (exception or 5xx) -> **everything is refunded**
   - client errors (4xx) stay charged, so spamming invalid requests is not free

### Overspend policy: bounded debt
When a request uses more than it was charged, the balance may go **negative**
("debt"), floored at `-capacity`. Alternatives considered:
- *Clamp to zero:* simple, but the overrun is forgiven, so a client could always
  under-declare `max_tokens` and get free tokens.
- *Unlimited debt:* one huge overrun could lock a client out for hours.
- *Bounded debt (chosen):* overruns are paid back through normal refill, and the
  worst-case lockout is capped at `2 x capacity / refill_rate` seconds.

## A request that can never fit
If one request costs more than the bucket's **capacity**, waiting cannot help.
tokenguard answers `413 request_too_large` (no `Retry-After`) instead of a
`429`, and never touches Redis for it. The client must send less.

## Known limitation: streaming
For streamed responses the real usage arrives at the end of the stream, after the
HTTP response has started. Reconciliation after streaming is future work.
