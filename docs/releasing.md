# Building and checking a release

The PyPI name is **`tokenguard-ratelimit`**; you import it as `tokenguard`.

```powershell
pip install build twine
python scripts/release_check.py metadata        # fields, LICENSE, versions agree
python scripts/release_check.py name            # is the name free on PyPI?
python -m build                                 # writes dist/*.whl and dist/*.tar.gz
twine check dist/*
python scripts/release_check.py wheel dist\tokenguard_ratelimit-0.6.0-py3-none-any.whl
python scripts/release_check.py install dist\tokenguard_ratelimit-0.6.0-py3-none-any.whl
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
