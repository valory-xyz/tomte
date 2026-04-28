"""Render a per-repo mypy.ini = tomte canonical + appended ini content."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from tomte.configs import MYPY_INI


def main(output: str, append_from: Optional[str] = None) -> None:
    canonical = MYPY_INI.read_text(encoding="utf-8")
    appended = Path(append_from).read_text(encoding="utf-8") if append_from else ""
    Path(output).write_text(canonical + "\n" + appended, encoding="utf-8")
