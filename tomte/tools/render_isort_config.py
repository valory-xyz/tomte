"""Render a per-repo isort.cfg = tomte canonical + repo-specific known_* keys."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from tomte.configs import ISORT_CFG


def main(
    output: str,
    known_first_party: Optional[str] = None,
    known_packages: Optional[str] = None,
    known_local_folder: Optional[str] = None,
) -> None:
    canonical = ISORT_CFG.read_text(encoding="utf-8")
    overrides = []
    if known_first_party:
        overrides.append(f"known_first_party = {known_first_party}")
    if known_packages:
        overrides.append(f"known_packages = {known_packages}")
    if known_local_folder:
        overrides.append(f"known_local_folder = {known_local_folder}")
    extra = ("\n" + "\n".join(overrides) + "\n") if overrides else ""
    Path(output).write_text(canonical + extra, encoding="utf-8")
