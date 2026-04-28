"""Canonical linter configuration resources shipped with tomte."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

_RESOURCE_ROOT = files(__package__)


def _path(filename: str) -> Path:
    return Path(str(_RESOURCE_ROOT / filename))


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
