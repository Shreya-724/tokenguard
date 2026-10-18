## Metrics

Turn on `"METRICS": True` and tokenguard records every decision in Redis (one
Lua call each): allowed and blocked per second, per rule, and per consumer, with
automatic expiry. Then ask it questions:

```python
from tokenguard.django.conf import get_metrics_reader

m = get_metrics_reader()
m.summary(60)  # requests, blocked ratio, requests/sec
m.top_consumers(n=5)  # who is using the most right now
m.timeseries(seconds=300)  # per second, for a chart
```

or `python scripts/tokenguard_stats.py top`. Details, storage layout and limits:
[docs/metrics.md](docs/metrics.md).
