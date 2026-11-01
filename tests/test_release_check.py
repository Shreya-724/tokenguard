"""The release checks: metadata, wheel contents, name lookup, username swap."""

import io
import json
import re
import shutil
import sys
import urllib.error
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import release_check as rc  # noqa: E402
import set_github_user as sgu  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def copy_project(dst):
    """A small copy of the project, with the username placeholder put back.

    The real files stop containing the placeholder once the author has run
    set_github_user.py, so the tests must not depend on that.
    """
    for name in ("pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md"):
        text = (ROOT / name).read_text("utf-8")
        text = re.sub(
            r"github\.com/(?:<your-username>|[A-Za-z0-9-]+)/tokenguard",
            "github.com/<your-username>/tokenguard",
            text,
        )
        (dst / name).write_text(text, "utf-8")
    (dst / "docs").mkdir()
    pkg = dst / "src" / "tokenguard"
    pkg.mkdir(parents=True)
    shutil.copy(ROOT / "src/tokenguard/__init__.py", pkg / "__init__.py")
    (pkg / "py.typed").write_text("")
    (pkg / "x.lua").write_text("return 1")
    return dst


def build_wheel(
    path, root, drop=(), extra=(), name="tokenguard-ratelimit", version=None
):
    project = rc.load_pyproject(root)["project"]
    version = version or project["version"]
    files = {
        "tokenguard/__init__.py": "",
        "tokenguard/py.typed": "",
        "tokenguard/x.lua": "return 1",
        "tokenguard/django/__init__.py": "",
        f"tokenguard_ratelimit-{version}.dist-info/licenses/LICENSE": "MIT",
        f"tokenguard_ratelimit-{version}.dist-info/METADATA": (
            "Metadata-Version: 2.4\n"
            f"Name: {name}\nVersion: {version}\nLicense-Expression: MIT\n"
            "Requires-Dist: redis>=5.0\n"
            "Provides-Extra: django\nProvides-Extra: drf\nProvides-Extra: dashboard\n"
        ),
    }
    for item in drop:
        files.pop(item, None)
    for item in extra:
        files[item] = ""
    with zipfile.ZipFile(path, "w") as wheel:
        for filename, content in files.items():
            wheel.writestr(filename, content)
    return path


def test_real_project_metadata_is_fine():
    assert rc.check_metadata(ROOT) == []


def test_placeholder_is_only_an_error_for_a_release(tmp_path):
    root = copy_project(tmp_path)
    text = (root / "pyproject.toml").read_text("utf-8")
    assert rc.PLACEHOLDER in text
    assert rc.check_metadata(root) == []
    assert any(rc.PLACEHOLDER in p for p in rc.check_metadata(root, release=True))


def test_version_mismatch_is_caught(tmp_path):
    root = copy_project(tmp_path)
    init = root / "src/tokenguard/__init__.py"
    init.write_text(
        init.read_text("utf-8").replace('__version__ = "', '__version__ = "9.')
    )
    assert any("differs" in p for p in rc.check_metadata(root))


def test_missing_files_are_caught(tmp_path):
    root = copy_project(tmp_path)
    (root / "LICENSE").unlink()
    (root / "src/tokenguard/py.typed").unlink()
    problems = " ".join(rc.check_metadata(root))
    assert "LICENSE" in problems and "py.typed" in problems


def test_changelog_needs_the_version(tmp_path):
    root = copy_project(tmp_path)
    (root / "CHANGELOG.md").write_text("# Changelog\n")
    assert any("CHANGELOG" in p for p in rc.check_metadata(root))


def test_good_wheel_passes(tmp_path):
    root = copy_project(tmp_path)
    wheel = build_wheel(tmp_path / "ok.whl", root)
    assert rc.check_wheel(wheel, root) == []


def test_wheel_missing_lua_and_py_typed(tmp_path):
    root = copy_project(tmp_path)
    wheel = build_wheel(
        tmp_path / "bad.whl", root, drop=("tokenguard/x.lua", "tokenguard/py.typed")
    )
    problems = " ".join(rc.check_wheel(wheel, root))
    assert "x.lua" in problems and "py.typed" in problems


def test_wheel_with_tests_and_wrong_name(tmp_path):
    root = copy_project(tmp_path)
    wheel = build_wheel(
        tmp_path / "bad.whl", root, extra=("tests/test_a.py",), name="tokenguard"
    )
    problems = " ".join(rc.check_wheel(wheel, root))
    assert "tests/" in problems and "Name" in problems


def test_wheel_wrong_version(tmp_path):
    root = copy_project(tmp_path)
    wheel = build_wheel(tmp_path / "v.whl", root, version="0.0.1")
    assert any("Version" in p for p in rc.check_wheel(wheel, root))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_name_taken_free_and_error():
    body = json.dumps({"info": {"name": "x", "version": "1", "summary": "s"}}).encode()
    assert (
        rc.check_name("x", fetch=lambda url, timeout: FakeResponse(body))[0] == "taken"
    )

    def missing(url, timeout):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    def broken(url, timeout):
        raise OSError("offline")

    assert rc.check_name("x", fetch=missing)[0] == "free"
    assert rc.check_name("x", fetch=broken)[0] == "error"


def test_set_github_user_replaces_and_is_repeatable(tmp_path):
    root = copy_project(tmp_path)
    (root / "docs" / "a.md").write_text(f"see {sgu.PLACEHOLDER}/x")
    changed = sgu.replace_in(root, "octocat")
    assert len(changed) >= 2
    assert sgu.PLACEHOLDER not in (root / "README.md").read_text("utf-8")
    assert "octocat" in (root / "docs" / "a.md").read_text("utf-8")
    assert sgu.replace_in(root, "octocat") == []
    assert rc.check_metadata(root, release=True) == []
