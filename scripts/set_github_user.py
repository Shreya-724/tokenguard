"""Replace the <your-username> placeholder with your GitHub username.

    python scripts/set_github_user.py octocat

Edits README.md, pyproject.toml and the files in docs/ in place, and prints each
file it changed. Safe to run twice.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "<your-username>"


def replace_in(root, username):
    """Returns the files changed."""
    changed = []
    files = [
        root / "README.md",
        root / "pyproject.toml",
        *sorted((root / "docs").glob("*.md")),
    ]
    for path in files:
        text = path.read_text("utf-8")
        if PLACEHOLDER in text:
            path.write_text(text.replace(PLACEHOLDER, username), "utf-8")
            changed.append(path.relative_to(root))
    return changed


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", argv[0]
    ):
        sys.exit(__doc__ + "\nGive a GitHub username (letters, digits, hyphens).")
    changed = replace_in(ROOT, argv[0])
    for path in changed:
        print("updated", path)
    print(f"{len(changed)} file(s) changed")


if __name__ == "__main__":
    main()
