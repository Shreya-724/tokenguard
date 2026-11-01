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
        and use it. Needs the internet for dependencies. Uses REDIS_URL if set.

Build first with:  python -m build
Exit status is 0 when every check passes, 1 otherwise.
"""

import argparse
import json
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
    if release:
        for name, url in urls.items():
            if PLACEHOLDER in url:
                problems.append(f"[project.urls] {name} still has {PLACEHOLDER}")
        if PLACEHOLDER in (root / "README.md").read_text("utf-8"):
            problems.append(f"README.md still has {PLACEHOLDER}")
    return problems


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
        return ok


def report(problems, ok_text):
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print("  -", problem)
        return 1
    print(ok_text)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    meta = sub.add_parser("metadata")
    meta.add_argument("--release", action="store_true")
    sub.add_parser("name")
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
    if args.command == "wheel":
        return report(check_wheel(args.path), f"{args.path} looks right")
    ok = check_install(args.path)
    print("install check passed" if ok else "INSTALL CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
