#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""Regression tests for `bump_to_latest.build_extra_flags`.

`build_extra_flags` exists specifically because the previous loop body
lossy-stripped `python = `, `markers = `, and `platform = ` qualifiers
when re-emitting `poetry add`. Re-introducing the same bug class would
silently downgrade every conditional dep (e.g. `tomli` is `python<3.11`-
only) into an unconditional dep on the next bump run.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# `bump_to_latest.py` lives at the repo root, not in a package. Load it
# by file path so the test does not depend on cwd or sys.path tricks.
_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "bump_to_latest", _ROOT / "bump_to_latest.py"
)
assert _SPEC and _SPEC.loader
bump_to_latest = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bump_to_latest)


def test_build_extra_flags_emits_all_qualifiers_in_stable_order() -> None:
    """All four qualifiers present → all four flags emitted, deterministic order."""
    meta = {
        "version": "==1.0.0",
        "optional": True,
        "python": "<3.11",
        "platform": "linux",
        "markers": "sys_platform == 'linux'",
    }
    flags = bump_to_latest.build_extra_flags(meta, optional_extra_name="cli")
    assert flags == [
        "--optional=cli",
        "--python=<3.11",
        "--platform=linux",
        "--markers=sys_platform == 'linux'",
    ]


def test_build_extra_flags_no_qualifiers_returns_empty() -> None:
    """Plain dep with no extras → empty flag list (no spurious flags)."""
    flags = bump_to_latest.build_extra_flags(
        {"version": "==1.0.0"}, optional_extra_name=None
    )
    assert flags == []


def test_build_extra_flags_preserves_python_marker_only() -> None:
    """The motivating regression: `python = "<3.11"` must round-trip.

    `tomli` in tomte's pyproject is conditional on python<3.11; if this
    flag were dropped it would be installed unconditionally, breaking
    py3.11+ envs that already have stdlib `tomllib`.
    """
    meta = {"version": "==2.0.1", "python": "<3.11", "optional": True}
    flags = bump_to_latest.build_extra_flags(meta, optional_extra_name="cli")
    assert "--python=<3.11" in flags
    assert "--optional=cli" in flags


def test_build_extra_flags_optional_without_extra_name_skipped() -> None:
    """`optional=true` without a discoverable [tool.poetry.extras] mapping →
    no `--optional=` flag (poetry rejects bare `--optional`)."""
    meta = {"version": "==1.0.0", "optional": True}
    flags = bump_to_latest.build_extra_flags(meta, optional_extra_name=None)
    assert flags == []


def test_build_extra_flags_pep508_markers_only() -> None:
    """`markers = "..."` round-trips even without python/platform."""
    meta = {
        "version": "==1.0.0",
        "markers": "python_version >= '3.12' and sys_platform != 'win32'",
    }
    flags = bump_to_latest.build_extra_flags(meta, optional_extra_name=None)
    assert flags == [
        "--markers=python_version >= '3.12' and sys_platform != 'win32'",
    ]
