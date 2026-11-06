# Building and checking a release

The PyPI name is **`tokenguard-ratelimit`**; you import it as `tokenguard`.

```powershell
pip install build twine
python scripts/release_check.py metadata        # fields, LICENSE, versions agree
python scripts/release_check.py name            # is the name free on PyPI?
python -m build                                 # writes dist/*.whl and dist/*.tar.gz
twine check dist/*
python scripts/release_check.py wheel dist\tokenguard_ratelimit-1.0.0-py3-none-any.whl
python scripts/release_check.py install dist\tokenguard_ratelimit-1.0.0-py3-none-any.whl
```

`install` makes a throwaway virtualenv, installs the wheel into it, imports the
package from outside the repo (so `src/` cannot hide a missing file), runs the three
algorithms against Redis if `REDIS_URL` is set, then installs the `[django,drf]`
extras. CI runs the same steps in the `package` job.

Before the real upload, set your GitHub username and re-check:

```powershell
python scripts/set_github_user.py <username>
python scripts/release_check.py metadata --release
```

## Extras

| Extra | Adds |
|---|---|
| `django` | Django |
| `drf` | Django REST framework (the staff-only metrics API) |
| `dashboard` | channels, channels-redis, daphne (live feed) |
| `bench` | Locust and friends for `benchmarks/` |
| `dev` | pytest, ruff, and the test tools |

## Version bumps

Change the version in three places: `pyproject.toml`, `src/tokenguard/__init__.py`
and a `## <version>` heading in `CHANGELOG.md`. `release_check.py metadata` fails if
they disagree.

## Publishing (Week 8, Day 2)

Do TestPyPI first. A version number can be uploaded to an index only once, ever, so
find mistakes there.

### Option A: by hand with an API token (simplest the first time)

1. Make accounts at <https://test.pypi.org> and <https://pypi.org> (they are
   separate) and turn on two-factor authentication on both.
2. On each, create an API token (Account settings -> API tokens). For the first
   upload the scope has to be "Entire account"; afterwards you can replace it with
   one limited to this project.
3. Upload:

```powershell
python -m build
twine check dist/*
twine upload --repository testpypi dist/*      # username: __token__  password: the token
python scripts/release_check.py index testpypi # installs it back from TestPyPI
```

4. When that passes, upload to the real index and check again:

```powershell
twine upload dist/*
python scripts/release_check.py index pypi
```

Never paste a token into a file in the repository. Twine asks for it, or reads
`TWINE_PASSWORD`.

### Option B: from GitHub Actions (no tokens stored)

`.github/workflows/release.yml` publishes using "trusted publishing". One-time setup,
on each index (PyPI: Account -> Publishing -> "Add a pending publisher"):

| Field | Value |
|---|---|
| Project name | `tokenguard-ratelimit` |
| Owner / repository | your GitHub username / `tokenguard` |
| Workflow name | `release.yml` |
| Environment | `pypi` on pypi.org, `testpypi` on test.pypi.org |

Then in GitHub: Settings -> Environments -> create `pypi` and `testpypi`.

- TestPyPI: Actions -> Release -> Run workflow.
- PyPI: push a tag (below). The workflow refuses if the tag and the version differ.

### Tagging

Once CI is green and TestPyPI works:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

A published version cannot be replaced. If something is wrong, bump to 1.0.1 and
"yank" the bad release on PyPI.

### Done when

```powershell
python -m venv $env:TEMP\final; & $env:TEMP\final\Scripts\pip install "tokenguard-ratelimit[django]"
& $env:TEMP\final\Scripts\python -c "import tokenguard; print(tokenguard.__version__)"
```

works from any directory and prints `1.0.0`.

## Before every upload: the checklist

An uploaded version can never be changed, so these run first. Each one has caught a
real mistake.

```powershell
python scripts/set_github_user.py <username>            # no <your-username> left
python scripts/release_check.py readme-links --write    # PyPI cannot follow docs/x.md
python scripts/release_check.py metadata --release      # must print "metadata looks right"
python -m build
twine check dist/*
python scripts/release_check.py wheel dist/<the .whl>   # also refuses placeholder links
python scripts/release_check.py install dist/<the .whl> # needs REDIS_URL (db 5)
```

Why `readme-links`: PyPI shows the README on its own page, so a relative link such as
`docs/demo.gif` points at nothing there. The command rewrites them to absolute GitHub
URLs, which also work on GitHub itself.

## When a release went out wrong

PyPI never lets you replace a published file, and a version number cannot be reused.
Fix the problem, give it a new version, and upload that.

```powershell
python scripts/bump_version.py 1.0.1 "Fix the project links shown on PyPI."
```

That edits `pyproject.toml`, `src/tokenguard/__init__.py` and `CHANGELOG.md`
together. Then run the checklist above, push, wait for CI, and tag `v1.0.1`.

To warn people off the bad version, open it on pypi.org (Manage -> Release options
-> Yank). A yanked version is still installable if someone pins it exactly, but pip
will not choose it otherwise.
