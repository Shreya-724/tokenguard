"""Checks to run before publishing (Week 8). Four subcommands:

    python scripts/release_check.py metadata [--release]
        pyproject.toml, LICENSE, version agreement, the typing marker. Offline.
        --release also fails on the <your-username> placeholder in the URLs.
    python scripts/release_check.py name
        Is the install name still free on PyPI (or yours)? Needs the internet.
    python scripts/release_check.py wheel dist/<name>.whl
        What is inside the built wheel, and what it says about itself.
    python scripts/release_check.py install dist/<name>.whl
        Install the wheel into a brand new virtualenv (with and without extras)
        and use it, then run the README quick start in a new Django project.
        Needs the internet for dependencies. Uses REDIS_URL if set (use db 5).

    python scripts/release_check.py tag v1.0.0
        Does the git tag match the version in pyproject.toml? (CI runs this.)
    python scripts/release_check.py index testpypi|pypi [VERSION]
        After uploading: install the package FROM the index into a fresh
        virtualenv and use it. VERSION defaults to the one in pyproject.toml.

    python scripts/release_check.py readme-links [--write] [--branch main]
        PyPI shows the README on its own page, so a relative link such as
        docs/algorithms.md breaks there. Lists them; --write rewrites them to
        absolute GitHub URLs (built from [project.urls] Source). Safe to repeat.

Build first with:  python -m build
Exit status is 0 when every check passes, 1 otherwise.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import venv
import zipfile
from email.parser import Parser
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = "<your-username>"
VERSION = re.compile(r"^\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?$")
REQUIRED_EXTRAS = {"django", "drf", "dashboard"}


def load_pyproject(root):
    with open(Path(root) / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)


def init_version(root):
    text = (Path(root) / "src" / "tokenguard" / "__init__.py").read_text("utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def check_metadata(root=ROOT, release=False):
    """A list of problems with the package metadata (empty = fine)."""
    root = Path(root)
    problems = []
    project = load_pyproject(root).get("project", {})
    for field in ("name", "version", "description", "readme", "requires-python"):
        if not project.get(field):
            problems.append(f"pyproject.toml: [project] {field} is missing")
    if not project.get("authors"):
        problems.append("pyproject.toml: [project] authors is missing")
    if not project.get("license"):
        problems.append("pyproject.toml: [project] license is missing")
    if not (root / "LICENSE").is_file():
        problems.append("LICENSE file is missing")
    if not (root / str(project.get("readme", "README.md"))).is_file():
        problems.append("the readme file named in pyproject.toml does not exist")
    if not (root / "src" / "tokenguard" / "py.typed").is_file():
        problems.append(
            "src/tokenguard/py.typed is missing (the 'Typing :: Typed' claim)"
        )
    classifiers = project.get("classifiers", [])
    if not classifiers:
        problems.append("pyproject.toml: no classifiers")
    if any(c.startswith("License ::") for c in classifiers):
        problems.append("remove the 'License ::' classifier: `license` already says it")
    if "Typing :: Typed" not in classifiers:
        problems.append("add the 'Typing :: Typed' classifier (py.typed exists)")
    version = project.get("version", "")
    if not VERSION.match(version):
        problems.append(f"version {version!r} is not a valid PEP 440 version")
    if init_version(root) != version:
        problems.append(
            f"__version__ ({init_version(root)}) differs from pyproject ({version})"
        )
    changelog = (root / "CHANGELOG.md").read_text("utf-8")
    if f"## {version}" not in changelog:
        problems.append(f"CHANGELOG.md has no '## {version}' entry")
    extras = set(project.get("optional-dependencies", {}))
    if not REQUIRED_EXTRAS <= extras:
        problems.append(f"missing extras: {sorted(REQUIRED_EXTRAS - extras)}")
    if not project.get("dependencies"):
        problems.append("pyproject.toml: no dependencies (redis is required)")
    urls = project.get("urls", {})
    if not urls:
        problems.append("pyproject.toml: no [project.urls]")
    readme_text = (root / str(project.get("readme", "README.md"))).read_text("utf-8")
    relative = relative_links(readme_text)
    if relative:
        shown = ", ".join(relative[:4]) + (" ..." if len(relative) > 4 else "")
        problems.append(
            f"README.md has {len(relative)} relative link(s) that break on PyPI "
            f"({shown}). "
            "Run: python scripts/release_check.py readme-links --write"
        )
    if release:
        for name, url in urls.items():
            if PLACEHOLDER in url:
                problems.append(f"[project.urls] {name} still has {PLACEHOLDER}")
        if PLACEHOLDER in (root / "README.md").read_text("utf-8"):
            problems.append(f"README.md still has {PLACEHOLDER}")
    return problems


SKIP_TARGET = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#|//)", re.IGNORECASE)
LINK = re.compile(r"(!?\[[^\]\n]*\])\(\s*([^)\s]+)((?:\s+\"[^\"]*\")?)\s*\)")
HTML_ATTR = re.compile(r"""(\b(?:src|href)=)(["'])([^"']+)\2""")
MEDIA = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp4", ".webm")


def _is_relative(target):
    return bool(target) and not SKIP_TARGET.match(target)


def _outside_fences(text):
    """Yield (is_code, line) so fenced code blocks are left alone."""
    fenced = False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            yield True, line
        else:
            yield fenced, line


def relative_links(text):
    """Targets of links and images that are relative (they break on PyPI)."""
    found = []
    for is_code, line in _outside_fences(text):
        if is_code:
            continue
        found += [m.group(2) for m in LINK.finditer(line) if _is_relative(m.group(2))]
        found += [
            m.group(3) for m in HTML_ATTR.finditer(line) if _is_relative(m.group(3))
        ]
    return found


def absolute_url(target, repo_url, branch="main", image=False):
    path, _, anchor = target.partition("#")
    path = path.removeprefix("./")
    owner_repo = repo_url.rstrip("/").removeprefix("https://github.com/")
    if image or path.lower().endswith(MEDIA):
        url = f"https://raw.githubusercontent.com/{owner_repo}/{branch}/{path}"
    elif path.endswith("/"):
        url = f"{repo_url.rstrip('/')}/tree/{branch}/{path}"
    else:
        url = f"{repo_url.rstrip('/')}/blob/{branch}/{path}"
    return url + (f"#{anchor}" if anchor else "")


def absolutize_readme(text, repo_url, branch="main"):
    """README text with every relative link made absolute. Idempotent."""
    out = []
    for is_code, line in _outside_fences(text):
        if not is_code:

            def link(match):
                if not _is_relative(match.group(2)):
                    return match.group(0)
                url = absolute_url(
                    match.group(2),
                    repo_url,
                    branch,
                    image=match.group(1).startswith("!"),
                )
                return f"{match.group(1)}({url}{match.group(3)})"

            def attr(match):
                if not _is_relative(match.group(3)):
                    return match.group(0)
                url = absolute_url(match.group(3), repo_url, branch, image=True)
                return f"{match.group(1)}{match.group(2)}{url}{match.group(2)}"

            line = HTML_ATTR.sub(attr, LINK.sub(link, line))
        out.append(line)
    return "".join(out)


def check_wheel(path, root=ROOT):
    """A list of problems with a built wheel (empty = fine)."""
    root = Path(root)
    problems = []
    with zipfile.ZipFile(path) as wheel:
        names = set(wheel.namelist())
        metadata_name = next(
            (n for n in names if n.endswith(".dist-info/METADATA")), None
        )
        if metadata_name is None:
            return [f"{path}: no METADATA inside the wheel"]
        metadata = Parser().parsestr(wheel.read(metadata_name).decode("utf-8"))
    for needed in ("tokenguard/__init__.py", "tokenguard/py.typed"):
        if needed not in names:
            problems.append(f"missing from the wheel: {needed}")
    for lua in sorted((root / "src" / "tokenguard").glob("*.lua")):
        if f"tokenguard/{lua.name}" not in names:
            problems.append(f"missing from the wheel: tokenguard/{lua.name}")
    if not any(n.startswith("tokenguard/django/") for n in names):
        problems.append("the tokenguard/django package is not in the wheel")
    for unwanted in ("tests/", "demo/", "dashboard/", "benchmarks/", "docs/"):
        if any(n.startswith(unwanted) for n in names):
            problems.append(f"the wheel contains {unwanted} (it should not)")
    expected = load_pyproject(root)["project"]
    if (
        metadata["Name"]
        and metadata["Name"].lower().replace("_", "-") != expected["name"]
    ):
        problems.append(f"wheel Name {metadata['Name']!r} != {expected['name']!r}")
    if metadata["Version"] != expected["version"]:
        problems.append(f"wheel Version {metadata['Version']} != {expected['version']}")
    for url in metadata.get_all("Project-URL") or []:
        if PLACEHOLDER in url:
            problems.append(f"the wheel's project link still has {PLACEHOLDER}: {url}")
    if PLACEHOLDER in metadata.as_string():
        problems.append(f"the wheel metadata still contains {PLACEHOLDER}")
    requires = metadata.get_all("Requires-Dist") or []
    if not any(r.lower().startswith("redis") and "extra ==" not in r for r in requires):
        problems.append("the wheel does not require redis")
    provided = set(metadata.get_all("Provides-Extra") or [])
    if not REQUIRED_EXTRAS <= provided:
        problems.append(f"the wheel lacks extras {sorted(REQUIRED_EXTRAS - provided)}")
    if not (metadata.get("License-Expression") or metadata.get("License")):
        problems.append("the wheel metadata names no license")
    if not any(n.endswith("licenses/LICENSE") or n.endswith("/LICENSE") for n in names):
        problems.append("the LICENSE file is not inside the wheel")
    return problems


def check_name(name, fetch=None):
    """('free' | 'taken' | 'error', detail) for a name on PyPI."""
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        with (fetch or urllib.request.urlopen)(url, timeout=15) as response:
            info = json.load(response)["info"]
        return (
            "taken",
            f"{info.get('name')} {info.get('version')}: {info.get('summary')}",
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return "free", f"{name} is not registered on PyPI"
        return "error", f"PyPI answered HTTP {exc.code}"
    except OSError as exc:
        return "error", f"could not reach PyPI: {exc}"


SMOKE = """
import tokenguard
from tokenguard import Limit, get_algorithm, algorithm_names
print("version", tokenguard.__version__)
assert algorithm_names() == ("token_bucket", "fixed_window", "sliding_window")
import os, redis
url = os.environ.get("REDIS_URL")
if url:
    client = redis.Redis.from_url(url, decode_responses=True)
    client.ping()
    for name in algorithm_names():
        algo = get_algorithm(name, client, key_prefix="relcheck:")
        rule = Limit(capacity=2, refill_rate=0.001)
        got = [algo.check("k", 1, rule).allowed for _ in range(3)]
        assert got == [True, True, False], (name, got)
    for key in client.scan_iter("relcheck:*"):
        client.delete(key)
    print("limiter works against Redis")
else:
    print("REDIS_URL not set: imported, but did not talk to Redis")
"""


def run(command, **kwargs):
    print("  $", " ".join(str(c) for c in command))
    return subprocess.run(command, check=False, **kwargs).returncode == 0


def check_install(wheel):
    """Install the wheel into a fresh virtualenv and use it. True when it works."""
    wheel = Path(wheel).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        env_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        python = env_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"
        ok = run([python, "-m", "pip", "install", "--quiet", str(wheel)])
        ok = ok and run([python, "-c", SMOKE], cwd=tmp)  # cwd: not the repo, so no src/
        extra = f"{wheel}[django,drf]"
        ok = ok and run([python, "-m", "pip", "install", "--quiet", extra])
        ok = ok and run(
            [
                python,
                "-c",
                "import django, rest_framework; "
                "from tokenguard.django import rate_limit; print('django extras ok')",
            ],
            cwd=tmp,
        )
        redis_url = os.environ.get("REDIS_URL")
        if ok and redis_url:
            print("  the README quick start, in a brand new Django project:")
            ok = run(
                [
                    python,
                    ROOT / "scripts" / "quickstart_check.py",
                    "--redis",
                    redis_url,
                ],
                cwd=tmp,
            )
        elif ok:
            print("  REDIS_URL not set: skipped the quick start check")
        return ok


INDEXES = {
    "testpypi": [
        "--index-url",
        "https://test.pypi.org/simple/",
        "--extra-index-url",
        "https://pypi.org/simple/",
    ],
    "pypi": [],
}


def check_tag(tag, root=ROOT):
    """Problems if a release tag does not match the package version."""
    version = load_pyproject(root)["project"]["version"]
    if tag.removeprefix("refs/tags/") != f"v{version}":
        return [f"tag {tag!r} does not match version {version} (expected v{version})"]
    return []


def check_index(index, version, root=ROOT, attempts=6, wait=10):
    """Install name==version from an index into a fresh virtualenv and use it.

    A fresh upload can take a short while to appear, so the install is retried.
    """
    import time

    name = load_pyproject(root)["project"]["name"]
    with tempfile.TemporaryDirectory() as tmp:
        env_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        python = env_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"
        spec = f"{name}[django,drf]=={version}"
        command = [python, "-m", "pip", "install", "--quiet", "--no-cache-dir"]
        command += INDEXES[index] + [spec]
        for attempt in range(1, attempts + 1):
            if run(command):
                break
            if attempt == attempts:
                return False
            print(f"  not there yet, retrying in {wait}s ({attempt}/{attempts})")
            time.sleep(wait)
        return run([python, "-c", SMOKE], cwd=tmp)


def report(problems, ok_text):
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print("  -", problem)
        return 1
    print(ok_text)
    return 0


def readme_links_command(write, branch):
    readme = ROOT / "README.md"
    text = readme.read_text("utf-8")
    relative = relative_links(text)
    if not relative:
        print("README.md has no relative links")
        return 0
    for target in relative:
        print("  relative:", target)
    if not write:
        print(f"{len(relative)} relative link(s). Run again with --write to fix them.")
        return 1
    repo_url = load_pyproject(ROOT)["project"].get("urls", {}).get("Source", "")
    if PLACEHOLDER in repo_url or not repo_url.startswith("https://github.com/"):
        print(f"[project.urls] Source is {repo_url!r}: run set_github_user.py first")
        return 1
    readme.write_text(absolutize_readme(text, repo_url, branch), "utf-8")
    print(f"rewrote {len(relative)} link(s) to point at {repo_url} ({branch})")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    meta = sub.add_parser("metadata")
    meta.add_argument("--release", action="store_true")
    sub.add_parser("name")
    links = sub.add_parser("readme-links")
    links.add_argument("--write", action="store_true")
    links.add_argument("--branch", default="main")
    sub.add_parser("tag").add_argument("tag")
    idx = sub.add_parser("index")
    idx.add_argument("index", choices=sorted(INDEXES))
    idx.add_argument("version", nargs="?")
    for command in ("wheel", "install"):
        sub.add_parser(command).add_argument("path")
    args = parser.parse_args(argv)

    if args.command == "metadata":
        return report(check_metadata(ROOT, args.release), "metadata looks right")
    if args.command == "name":
        name = load_pyproject(ROOT)["project"]["name"]
        status, detail = check_name(name)
        print(f"{name}: {status}. {detail}")
        if status == "taken":
            print(
                "If this is YOUR earlier upload, that is fine. "
                "Otherwise pick another name."
            )
        return 0 if status == "free" else 1
    if args.command == "readme-links":
        return readme_links_command(args.write, args.branch)
    if args.command == "tag":
        return report(check_tag(args.tag), f"{args.tag} matches the version")
    if args.command == "index":
        version = args.version or load_pyproject(ROOT)["project"]["version"]
        ok = check_index(args.index, version)
        print(f"{args.index} install passed" if ok else "INSTALL FROM INDEX FAILED")
        return 0 if ok else 1
    if args.command == "wheel":
        return report(check_wheel(args.path), f"{args.path} looks right")
    ok = check_install(args.path)
    print("install check passed" if ok else "INSTALL CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
