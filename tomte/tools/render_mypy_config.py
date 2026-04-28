"""Render a per-repo mypy.ini = tomte canonical + repo's [mypy*] sections.

Reads canonical mypy.ini and the consumer's `--append-from=` file (typically
`tox.ini`), extracts every `[mypy*]` section from both, merges them with the
consumer's values winning for duplicate keys, writes a single ini file with
no duplicate sections.

Why merge (instead of plain concat): configparser in strict mode rejects
duplicate sections, and mypy's own ini parser uses strict mode. A naive
concat that ends up with two `[mypy]` sections breaks mypy at startup.
"""

from __future__ import annotations

import configparser
from pathlib import Path
from typing import Optional

from tomte.configs import MYPY_INI


def main(output: str, append_from: Optional[str] = None) -> None:
    merged = configparser.ConfigParser(strict=False)
    merged.read(MYPY_INI, encoding="utf-8")
    if append_from:
        overlay = configparser.ConfigParser(strict=False)
        overlay.read(append_from, encoding="utf-8")
        for section in overlay.sections():
            if not section.startswith("mypy"):
                continue
            if not merged.has_section(section):
                merged.add_section(section)
            for key, value in overlay.items(section):
                merged.set(section, key, value)
    # Drop non-[mypy*] sections (configparser may have read them from append_from)
    for section in list(merged.sections()):
        if not section.startswith("mypy"):
            merged.remove_section(section)
    with Path(output).open("w", encoding="utf-8") as handle:
        merged.write(handle)
