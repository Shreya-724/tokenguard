"""Set a new version in every place that holds it, and start its changelog entry.

    python scripts/bump_version.py 1.0.1 "Fix the project links shown on PyPI."

Edits pyproject.toml, src/tokenguard/__init__.py and CHANGELOG.md. Does not touch
git or PyPI. Afterwards run:  python scripts/release_check.py metadata --release
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = re.compile(r"^\d+\.\d+\.\d+((a|b|rc)\d+)?$")


def bump(root, version, note):
    """Apply the change; returns the files written. Raises ValueError on bad input."""
    root = Path(root)
    if not VERSION.match(version):
        raise ValueError(f"{version!r} is not a version like 1.0.1")
    pyproject = root / "pyproject.toml"
    init = root / "src" / "tokenguard" / "__init__.py"
    changelog = root / "CHANGELOG.md"

    text = pyproject.read_text("utf-8")
    new, count = re.subn(
        r'^version = "[^"]+"', f'version = "{version}"', text, count=1, flags=re.M
    )
    if count != 1:
        raise ValueError("no `version = ...` line in pyproject.toml")
    pyproject.write_text(new, "utf-8")

    text = init.read_text("utf-8")
    new, count = re.subn(
        r'^__version__ = "[^"]+"',
        f'__version__ = "{version}"',
        text,
        count=1,
        flags=re.M,
    )
    if count != 1:
        raise ValueError("no `__version__ = ...` line in __init__.py")
    init.write_text(new, "utf-8")

    text = changelog.read_text("utf-8")
    if f"## {version}\n" in text:
        raise ValueError(f"CHANGELOG.md already has a '## {version}' entry")
    entry = f"## {version}\n\n{note.strip() or 'TODO: describe this release.'}\n\n"
    first = re.search(r"^## ", text, re.M)
    if first is None:
        raise ValueError("CHANGELOG.md has no '## ' entry to put this one before")
    changelog.write_text(text[: first.start()] + entry + text[first.start() :], "utf-8")
    return [pyproject, init, changelog]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not 1 <= len(argv) <= 2:
        sys.exit(__doc__)
    try:
        files = bump(ROOT, argv[0], argv[1] if len(argv) > 1 else "")
    except ValueError as exc:
        sys.exit(f"error: {exc}")
    for path in files:
        print("updated", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
