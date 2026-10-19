"""Which rules exist: DEFAULT_RULE, RULES from settings, and @rate_limit views.

The admin API lists and changes rules by name (their scope), so it needs to know
them. Settings rules are read on demand; decorated views register themselves
when the decorator runs (at import time, before the first request).
"""

from __future__ import annotations

from tokenguard.django.conf import get_setting
from tokenguard.django.engine import Rule
from tokenguard.django.middleware import rule_from_spec

_VIEW_RULES: dict[str, Rule] = {}


def register_rule(rule: Rule) -> None:
    """Called by @rate_limit. A later rule with the same scope replaces it."""
    _VIEW_RULES[rule.scope] = rule


def known_rules() -> dict[str, tuple[str, Rule]]:
    """scope -> (source, rule); source is "default", "settings" or "view"."""
    found: dict[str, tuple[str, Rule]] = {
        "default": ("default", rule_from_spec(get_setting("DEFAULT_RULE"), "default"))
    }
    for spec in get_setting("RULES"):
        scope = spec.get("name", spec["match"])
        found[scope] = ("settings", rule_from_spec(spec, scope))
    for scope in sorted(_VIEW_RULES):
        found.setdefault(scope, ("view", _VIEW_RULES[scope]))
    return found
