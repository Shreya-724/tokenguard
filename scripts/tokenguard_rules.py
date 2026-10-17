"""Change tokenguard's rules live, from the command line.

    python scripts/tokenguard_rules.py list
    python scripts/tokenguard_rules.py set login --capacity 20 --refill-rate 2
    python scripts/tokenguard_rules.py set default --algorithm fixed_window
    python scripts/tokenguard_rules.py delete login

The rule NAME is the rule's scope: "default" for DEFAULT_RULE, the "name" of a
RULES entry, or a decorated view's scope (for example demo_site.views.fixed).
`set` replaces the whole override for that name, so give every field you want.
Servers need "LIVE_RULES": True and pick the change up within LIVE_RULES_TTL
seconds. Options, given before the command: --redis-url (default $REDIS_URL)
and --prefix (default "tg", the KEY_PREFIX setting).
"""

import argparse
import os
import sys

import redis

from tokenguard.rulestore import RuleStore


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--redis-url", default=os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    parser.add_argument("--prefix", default="tg", help="the KEY_PREFIX setting")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="show every override and the version")
    put = commands.add_parser("set", help="set (replace) an override")
    put.add_argument("name")
    put.add_argument("--capacity", type=float)
    put.add_argument("--refill-rate", type=float)
    put.add_argument("--algorithm")
    remove = commands.add_parser("delete", help="remove an override")
    remove.add_argument("name")
    args = parser.parse_args(argv)

    client = redis.Redis.from_url(args.redis_url, decode_responses=True)
    store = RuleStore(client, key_prefix=f"{args.prefix}:", ttl=0)
    try:
        if args.command == "list":
            rules = store.snapshot()
            print(f"rules version {rules.version}")
            for name, o in sorted(rules.overrides.items()):
                print(
                    f"  {name}: capacity={o.capacity} "
                    f"refill_rate={o.refill_rate} algorithm={o.algorithm}"
                )
            if not rules.overrides:
                print("  (no overrides: everything uses the settings)")
        elif args.command == "set":
            version = store.set_rule(
                args.name, args.capacity, args.refill_rate, args.algorithm
            )
            print(f"ok: rules version is now {version}")
        else:
            version = store.delete_rule(args.name)
            print("no such override" if version is None else f"ok: version {version}")
    except ValueError as exc:
        sys.exit(f"error: {exc}")
    return 0


if __name__ == "__main__":
    main()
