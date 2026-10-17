"""The version in the code and in pyproject.toml must not drift apart."""

import re
from pathlib import Path

import tokenguard

ROOT = Path(__file__).resolve().parent.parent


def test_the_package_version_matches_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert declared and declared.group(1) == tokenguard.__version__


def test_the_changelog_has_an_entry_for_this_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {tokenguard.__version__}" in changelog


def test_the_public_names_import():
    for name in tokenguard.__all__:
        assert hasattr(tokenguard, name)
