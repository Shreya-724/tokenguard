## Live rule changes

Change a limit while the server runs, with no redeploy. Rules live in Redis, every
process caches them for a few seconds, and each change bumps a version number.

```python
TOKENGUARD = {"LIVE_RULES": True, "LIVE_RULES_TTL": 5}  # off by default
```

```bash
python scripts/tokenguard_rules.py set login --capacity 20 --refill-rate 2
python scripts/tokenguard_rules.py delete login          # back to the settings
```

- A change reaches every server within `LIVE_RULES_TTL` seconds, and requests never
  wait on Redis for it (they read the cached copy).
- You can change `capacity`, `refill_rate` and `algorithm` of the default rule, a
  `RULES` entry, or a decorated view. Responses show the version in
  `X-TokenGuard-Rules-Version`.
- If Redis is down the last known rules keep being used. Bad values are rejected,
  and an override that cannot apply is ignored.

Details, what happens to existing counters, and a demo (`scripts/demo_live_rules.py`):
[docs/live-rules.md](docs/live-rules.md).
