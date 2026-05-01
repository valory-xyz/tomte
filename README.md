# tomte
A library that wraps many useful tools (linters, analysers, etc) to keep Python code clean, secure, well-documented and optimised.

Essentially does nothing else but pinning multiple packages to compatible versions, for consistency across many projects and simplicity of use.

Extremely (!) opinionated by design!

## Wrapped tools

- black
- bandit
- isort
- flake8
- mypy
- safety
- darglint
- vulture
- pylint
- docs (various mkdocs libraries)
- tests (various pytest libraries)
- tox
- liccheck

To install, for instance `black`, simply specify `tomte[black]==VERSION`, where `VERSION` is the latest version, and then use `black` CLI as required.

## Shipped configs

Since 0.7.0, tomte ships canonical linter configurations as packaged
resources. Reach them from a tox env (or any tooling) via:

```python
from tomte.configs import PYLINTRC, MYPY_INI, ISORT_CFG, FLAKE8_CFG, DARGLINT_CFG, BANDIT_YAML, SAFETY_POLICY
```

Each constant is a `pathlib.Path` to the file inside the installed
wheel. Typical use:

```ini
[testenv:pylint]
commands = pylint --rcfile={envsitepackagesdir}/tomte/configs/pylintrc <paths>
```

## `tomte tox` runtime wrapper

Since 0.7.0, `tomte tox` renders the canonical `tox.ini` (shipped at
`tomte/configs/tox.ini`) at runtime, reading per-repo identity from
`[tool.tomte]` in the consumer's `pyproject.toml` and a slim
`[tomte-extensions]` section in their local `tox.ini`. The rendered file
is ephemeral — nothing generated lives on disk between runs. Invoke as a
drop-in replacement: `tomte tox -e <env>`.

**Per-repo settings in `[tool.tomte]`** (TOML in `pyproject.toml`):
`packages_paths`, `pytest_targets[_extra|_exclude]`,
`service_specific_packages[_extra]`, `service_public_id`,
`known_first_party`, `open_autonomy_version`, `open_aea_version`,
`check_handlers_ignores`, `check_dependencies_extra_excludes`,
`upstream_pins`, `gitleaks_extra_paths`, `gitleaks_extra_regexes`,
`tomte_dep_pin`. Most defaults auto-derive from `packages.json`.

**Per-repo settings in `[tomte-extensions]`** (raw INI in local `tox.ini`,
for things that don't fit cleanly in TOML): `extra_deps`,
`extra_pylint_disables`, `extra_pylint_ignored_modules`,
`extra_testenvs` — multi-line continuation values that configparser
preserves verbatim.

**Scope.** `tomte tox` targets *AEA agent repos* — the homogeneous fleet
that ships `packages/valory/` skills + agents + services and bootstraps
via the `autonomy` CLI. Framework repos (`open-aea`, `open-autonomy`)
keep their own hand-written `tox.ini` and consume the canonical configs
directly (`from tomte.configs import PYLINTRC, MYPY_INI, …`) via
`--rcfile=` / `--config=` flags.

## Pytest plugin (opt-in)

Tomte declares a `pytest11` entry-point plugin in `pyproject.toml` that
ships fleet-canonical pytest defaults: the `integration` and `e2e`
markers, plus an `ignore::DeprecationWarning:aea.*:` filter. Pytest
auto-loads pytest11 plugins, so the plugin module is imported in any
environment where tomte is installed — but the plugin is **silent by
default**; it registers nothing unless the consumer opts in:

```ini
# tox.ini (or pyproject.toml [tool.pytest.ini_options], or pytest.ini)
[pytest]
tomte_defaults = true
```

Truthy spellings: `true`, `1`, `yes`, `on` (case-insensitive). Without
opt-in, non-fleet `tomte[black]` / `tomte[mypy]` consumers see no
config injection.

## Development:

### Install deps:

Install poetry.
Install development dependencies before running maintenance scripts:

`poetry install --with dev`

### Upgrading versions

Use the script directly (fully automated, no manual pin editing):

1. Run `poetry run python bump_to_latest.py`

This command automatically:

- Resolves latest compatible versions for `<4,>=3.10` support.
- Applies strict `==` pins with Poetry.
- Falls back to the highest resolver-compatible version when the absolute latest conflicts.
- Bumps package version (patch by default) in `pyproject.toml`, `tomte/__init__.py`, and `tests/test_tomte.py`.
- Regenerates `poetry.lock`.

Useful flags:

- `--dry-run`
- `--bump-version none|patch|minor|major`
- `--no-lock`

## Name

["The Swedish hustomte (house elf/gnome) is a quiet little guy, dressed mostly in gray and red, living at your house or farmsted helping out by taking care of things around the house and keep everyone safe."](https://funflector.com/blog/the-quiet-swedish-tomte/)

![A tomte and his son enjoying quiet company of the cat. Illustration by Rolf Lidberg.](https://github.com/valory-xyz/tomte/blob/main/tomte_and_cat_by_swedish_artist_rolf_lidberg.jpg?raw=true)

"A tomte and his son enjoying quiet company of the cat. Illustration by Rolf Lidberg."

## Release guide:

Finish edits and ensure dev dependencies are installed (`poetry install --with dev`), then run `poetry run python bump_to_latest.py`, then `poetry run pytest -q`, then `poetry build`, then `rm -rf dist`, then `poetry publish --build --username=<username> --password=<password>`.
