## Algorithms: which one should I use?

tokenguard has three algorithms behind one interface. Pick one globally with
`TOKENGUARD["ALGORITHM"]`, per route with `"algorithm"` in a rule, or per view with
`@rate_limit(..., algorithm="...")`.

| | `token_bucket` (default) | `fixed_window` | `sliding_window` |
|---|---|---|---|
| Most in any window-length span | 2 x capacity | 2 x capacity (at the edge) | exactly capacity |
| Memory per key | 120 bytes | 120 bytes | ~130 bytes per request in the window |
| Time per check | O(1) | O(1) | O(requests in the window) |
| Works with budgets | yes | no | no |

- **Token bucket**: the default. Cheapest, bursts on purpose, and the only one that
  works with budgets and settled LLM token costs.
- **Fixed window**: simplest to explain, but a client can use two windows' worth
  around an edge.
- **Sliding window**: never more than the limit in any span. Use it for hard limits
  with small numbers (tens of requests per key), since memory and time grow with the
  requests in the window.

Details, the boundary-burst demonstration and reproducible numbers:
[docs/algorithms.md](docs/algorithms.md). Run `python scripts/compare_algorithms.py`
to measure them on your own machine.
