# Documentation

| Page | What it covers |
|---|---|
| [cost-model.md](cost-model.md) | Token estimates, model weights, reconciliation, budgets, near-limit alerts, streaming |
| [algorithms.md](algorithms.md) | Token bucket, fixed window, sliding window: comparison and which to use |
| [live-rules.md](live-rules.md) | Changing limits while the server runs, and how changes spread |
| [race-condition.md](race-condition.md) | The check-then-act race, reproduced and fixed with Lua |

Reproducible numbers: `python scripts/compare_algorithms.py`.
