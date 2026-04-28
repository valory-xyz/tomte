"""
Canonical linter configuration resources shipped with tomte.

The architectural rule (set with David, 2026-04):

  * ``pyproject.toml`` stays strictly PEP 621 — no ``[tool.<linter>]``
    blocks anywhere, including no ``[tool.mypy]`` and no
    ``[tool.pytest.ini_options]``.
  * Every linter's canonical config lives here, in tomte. The lists are
    fleet unions; they're loose enough that 95%+ of repos need zero
    overrides.
  * Per-repo overrides (when a repo genuinely needs to deviate) live in
    that repo's ``tox.ini``, not in pyproject.toml. Tox is allowed to
    grow; pyproject is allowed to stay neat.

Each constant below is a ``pathlib.Path`` to the resource on disk.
Tox envs reach the canonicals via the ``--config=`` / ``--rcfile=`` /
``--settings-path=`` flag (whatever the linter accepts). The canonical
``tomte/templates/tox.ini.template`` (rendered by ``tomte scaffold
tox``) wires this up.

The mypy env is the only one with a slight twist: mypy parses
``[mypy*]`` sections out of any ini-format file, so the canonical tox
env concatenates ``MYPY_INI`` with the consuming repo's ``tox.ini`` at
runtime and points mypy at the merged file. That lets a repo append
``[mypy-foo.*]`` sections to its own ``tox.ini`` and have them layer
cleanly on top of the fleet defaults — without any ``[tool.mypy]`` in
pyproject.toml.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

_RESOURCE_ROOT = files(__package__)


def _path(filename: str) -> Path:
    return Path(str(_RESOURCE_ROOT / filename))


# Module-level path constants. Use these directly in tox env commands:
#
#   commands = pylint --rcfile={env:PYTHONPATH}/tomte/configs/pylintrc ...
#   commands = pylint --rcfile=$(python -c "from tomte.configs import PYLINTRC; print(PYLINTRC)") ...
#
# Constants over getter-functions because: (1) shell ergonomics — no `()`
# in the one-liner; (2) these are constants — the path of a packaged
# file doesn't change at runtime; (3) tab-completion friendly in REPL.

PYLINTRC: Path = _path("pylintrc")
MYPY_INI: Path = _path("mypy.ini")
ISORT_CFG: Path = _path("isort.cfg")
FLAKE8_CFG: Path = _path("flake8.cfg")
DARGLINT_CFG: Path = _path("darglint.cfg")
BANDIT_YAML: Path = _path("bandit.yaml")
SAFETY_POLICY: Path = _path("safety-policy.yml")
GITLEAKS_TOML: Path = _path("gitleaks.toml")


__all__ = [
    "PYLINTRC",
    "MYPY_INI",
    "ISORT_CFG",
    "FLAKE8_CFG",
    "DARGLINT_CFG",
    "BANDIT_YAML",
    "SAFETY_POLICY",
    "GITLEAKS_TOML",
]
