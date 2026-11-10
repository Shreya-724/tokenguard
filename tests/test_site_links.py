"""scripts/check_site_links.py: finding the links (no network)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_site_links as cl  # noqa: E402

SOURCE = """
export const GITHUB = "https://github.com/octocat/tokenguard";
const PYPI = "https://pypi.org/project/tokenguard-ratelimit/";
const docs = (name) => `${GITHUB}/blob/main/docs/${name}`;
<a href={docs("race-condition.md")}>a</a>
<a href={`${GITHUB}/issues`}>b</a>
<a href={`${GITHUB}#quick-start-5-minutes`}>c</a>
"""


def test_expands_the_constants_and_helpers():
    urls = cl.site_links(SOURCE)
    assert "https://github.com/octocat/tokenguard" in urls
    assert (
        "https://github.com/octocat/tokenguard/blob/main/docs/race-condition.md" in urls
    )
    assert "https://github.com/octocat/tokenguard/issues" in urls
    assert "https://pypi.org/project/tokenguard-ratelimit/" in urls
    assert all("#" not in u and "${" not in u for u in urls)


def test_finds_the_real_home_page_links():
    source = "\n".join(p.read_text("utf-8") for p in sorted(cl.HOME.glob("*.jsx")))
    urls = cl.site_links(source)
    assert len(urls) >= 6
    assert all(u.startswith("https://") and "${" not in u for u in urls)
