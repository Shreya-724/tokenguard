"""Check that every outside link on the home page really opens.

    python scripts/check_site_links.py

Reads the links out of dashboard/src/home/*.jsx and requests each one. Prints a
line per link and exits 1 if any does not answer 200. Needs the internet, so it
is a check to run by hand before a release, not part of the test suite.
"""

import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = ROOT / "dashboard" / "src" / "home"


def site_links(source):
    """Every http(s) URL the page can link to, with GITHUB / docs() expanded."""
    github = re.search(r'GITHUB = "([^"]+)"', source)
    pypi = re.search(r'PYPI = "([^"]+)"', source)
    github = github.group(1) if github else None
    urls = set(re.findall(r'"(https?://[^"\s]+)"', source))
    if github:
        urls.add(github)
        for name in re.findall(r'docs\("([^"]+)"\)', source):
            urls.add(f"{github}/blob/main/docs/{name}")
        for path in re.findall(r"\$\{GITHUB\}([^`\"\s}]*)", source):
            urls.add(github + path)
    if pypi:
        urls.add(pypi.group(1))
    # fragments are not sent to servers; a leftover template placeholder is not a link
    return sorted(u.split("#")[0] for u in urls if "${" not in u)


def check(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "tokenguard-link-check"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError as exc:
        return f"unreachable ({exc})"


def main():
    source = "\n".join(path.read_text("utf-8") for path in sorted(HOME.glob("*.jsx")))
    urls = sorted(set(site_links(source)))
    failed = 0
    for url in urls:
        status = check(url)
        ok = status == 200
        failed += not ok
        print(f"{'ok ' if ok else 'BAD'} {status}  {url}")
    print(f"{len(urls) - failed} of {len(urls)} links open")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
