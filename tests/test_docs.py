"""The documentation must keep matching the code it describes."""

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

README = (ROOT / "README.md").read_text("utf-8")
CONFIGURATION = (ROOT / "docs" / "configuration.md").read_text("utf-8")
EXAMPLES = (ROOT / "docs" / "examples.md").read_text("utf-8")


def default_settings():
    """The keys of DEFAULTS in conf.py, read without importing Django."""
    tree = ast.parse((ROOT / "src/tokenguard/django/conf.py").read_text("utf-8"))
    for node in ast.walk(tree):
        target = getattr(node, "target", None)
        if isinstance(target, ast.Name) and target.id == "DEFAULTS":
            return [key.value for key in node.value.keys]
    raise AssertionError("DEFAULTS not found in conf.py")


def code_blocks(text, language):
    return re.findall(rf"```{language}\n(.*?)```", text, re.DOTALL)


def test_every_setting_is_documented_in_the_readme_and_the_reference():
    settings = default_settings()
    assert len(settings) >= 15
    for name in settings:
        assert f"| `{name}` |" in README, f"{name} is missing from the README table"
        assert f"| `{name}` |" in CONFIGURATION, (
            f"{name} is missing from configuration.md"
        )


def test_the_examples_are_valid_python():
    blocks = code_blocks(EXAMPLES, "python")
    assert len(blocks) >= 12
    for block in blocks:
        ast.parse(block)


def test_the_quick_start_matches_what_quickstart_check_runs():
    import quickstart_check as qs

    for needle in (
        qs.MIDDLEWARE,
        '@rate_limit(capacity=5, refill_rate=0.1, key="ip")',
        'path("ping/", ping)',
        'pip install "tokenguard-ratelimit[django]"',
        "django-admin startproject mysite",
    ):
        assert needle in README, f"README quick start lost: {needle}"
    assert '@rate_limit(capacity=5, refill_rate=0.1, key="ip")' in qs.URLS


def test_the_readme_quick_start_python_blocks_are_valid():
    start = README.index("## Quick start")
    end = README.index("\n## ", start + 5)
    for block in code_blocks(README[start:end], "python"):
        ast.parse(block)


def test_no_placeholder_numbers_are_left_in_the_docs():
    for text in (README, CONFIGURATION, EXAMPLES):
        assert "<N>" not in text


def test_local_links_point_at_files_that_exist():
    # docs/ in this checkout may be a partial copy, so only check links to files
    # that this change set owns, plus the README's own scripts.
    owned = {
        "docs/configuration.md",
        "docs/examples.md",
        "docs/race-condition.md",
        "docs/releasing.md",
        "scripts/race_demo.py",
        "scripts/quickstart_check.py",
    }
    for name in owned:
        assert (ROOT / name).is_file(), name
    for target in re.findall(r"\]\((docs/[^)#]+|scripts/[^)#]+)", README):
        if target in owned:
            assert (ROOT / target).is_file()


DJANGO_TEMPLATE_MIDDLEWARE = """MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]
"""


def test_patch_settings_handles_djangos_single_quoted_template():
    import quickstart_check as qs

    for text in (
        DJANGO_TEMPLATE_MIDDLEWARE,
        DJANGO_TEMPLATE_MIDDLEWARE.replace("'", '"'),
        DJANGO_TEMPLATE_MIDDLEWARE.replace("\n", "\r\n"),
    ):
        patched = qs.patch_settings(text, "redis://x:1/5", "pfx")
        compile(patched, "settings.py", "exec")
        lines = [line.strip() for line in patched.splitlines()]
        auth = next(
            i for i, line in enumerate(lines) if "AuthenticationMiddleware" in line
        )
        assert "TokenGuardMiddleware" in lines[auth + 1]
        assert '"REDIS_URL": "redis://x:1/5"' in patched
        assert '"KEY_PREFIX": "pfx"' in patched


def test_patch_settings_explains_when_the_anchor_is_missing():
    import quickstart_check as qs

    with pytest.raises(SystemExit):
        qs.patch_settings("MIDDLEWARE = []\n", "redis://x/5", "p")
