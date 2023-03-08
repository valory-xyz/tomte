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

## Development:

### Install deps:

Install poetry.

### Upgrading versions

Currently, the following, somewhat hacky, process works well:

1. Run `sed -i '' "s/==/>=/g" pyproject.toml` to remove strict version requirements.

2. `poetry shell` and `pip install toml requests`

3. Run `python ./bump_to_latest.py`

4. Check non-strict versions in `pyproject.toml` and make them strict by manually running the `poetry add PACKAGE@==VERSION --optional`. Finaly, run `poetry update`

## Name

["The Swedish hustomte (house elf/gnome) is a quiet little guy, dressed mostly in gray and red, living at your house or farmsted helping out by taking care of things around the house and keep everyone safe."](https://funflector.com/blog/the-quiet-swedish-tomte/)

![A tomte and his son enjoying quiet company of the cat. Illustration by Rolf Lidberg.](https://github.com/valory-xyz/tomte/blob/main/tomte_and_cat_by_swedish_artist_rolf_lidberg.jpg?raw=true)

"A tomte and his son enjoying quiet company of the cat. Illustration by Rolf Lidberg."

## Release guide:

Finish edits, bump versions in `pyproject.toml` and `tomte/__init__.py`, then `poetry lock`, then `rm -rf dist`, then `poetry publish --build --username=<username> --password=<password>`.
