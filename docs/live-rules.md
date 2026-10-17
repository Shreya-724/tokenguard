# Live rule changes

Change a limit while the server runs: no redeploy, no restart.

```python
from tokenguard.rulestore import RuleStore

store = RuleStore(redis_client, key_prefix="tg:")
store.set_rule("login", capacity=20, refill_rate=2)  # bump a limit
store.set_rule("default", algorithm="sliding_window")  # change an algorithm
store.delete_rule("login")  # back to the settings
```

or from a shell:

```bash
python scripts/tokenguard_rules.py list
python scripts/tokenguard_rules.py set login --capacity 20 --refill-rate 2
python scripts/tokenguard_rules.py delete login
```

## Turning it on

```python
TOKENGUARD = {
    # ...
    "LIVE_RULES": True,  # off by default
    "LIVE_RULES_TTL": 5,  # seconds a process caches the live rules
}
```

## What can be changed

A live override changes one rule's **`capacity`**, **`refill_rate`** and/or
**`algorithm`**. A field you leave out keeps its configured value. Everything else
(key function, cost, budgets, fail mode) stays in settings.

The override's **name** is the rule's scope:

| Rule | Name |
|---|---|
| `DEFAULT_RULE` | `default` |
| a `RULES` entry | its `"name"` (for example `login`) |
| a view with `@rate_limit` | `<module>.<function>` (for example `demo_site.views.fixed`) |

`set_rule` replaces the whole override for that name. Bad values (zero, negative,
NaN, an unknown algorithm) are rejected before anything is stored.

## How a change spreads

```
admin: set_rule(...)  ->  Redis hash "<prefix>:{rules}"  (version +1, atomically)
                                   |
        each server process: reads it at most once per LIVE_RULES_TTL seconds,
        serves every request from its cached copy in between
```

- **Propagation delay:** a change reaches every server within `LIVE_RULES_TTL`
  seconds (plus one Redis read). The process that makes the change sees it at
  once. The default is 5 seconds; lower it for faster changes at the price of one
  Redis read per process per interval, still nothing per request.
- **No Redis call per request:** between refreshes the check is a dictionary lookup.
- **Rules version:** every change bumps a number that only goes up. Responses carry
  it as `X-TokenGuard-Rules-Version`, so you can see which version served a request.
- **Redis down:** servers keep using the last rules they loaded and try again after
  another interval. They never fail a request because of it. A server that never
  reached Redis simply uses the configured rules.
- **Bad data:** a damaged or invalid stored override is logged and ignored.
- **An override that cannot apply** (for example a fixed window on a rule with a
  budget) is logged and ignored; the configured rule stays in force.

## What happens to existing counters

- **Lowering `capacity`** applies at once: a bucket holding more than the new
  capacity is cut down to it.
- **Raising `capacity`** does not hand out tokens: the bucket fills at the refill
  rate (raise `refill_rate` too to fill faster).
- **Changing a window algorithm's `capacity` or `refill_rate`** changes its window
  length, so it starts a fresh window.
- **Changing the `algorithm`** starts fresh: each algorithm keeps its own state, so
  the new one starts with a full allowance.

## Notes

- The rules live in one Redis hash with no expiry. Do not run that database with an
  eviction policy such as `allkeys-lru` unless you accept rules being evicted.
- Anything that can write to Redis can change your limits. Protect it like any
  other control plane. (A rules API for the dashboard comes in Week 6.)
- Tested: `tests/test_rulestore.py` (store, cache, propagation delay, outages) and
  `tests/test_dj_live_rules.py` (through Django).

## Try it

Add two lines to the `TOKENGUARD` dict in `demo/demo_site/settings.py`:

```python
    "LIVE_RULES": True,
    "LIVE_RULES_TTL": 2,
```

then, with the server running:

```bash
python scripts/demo_live_rules.py
```
