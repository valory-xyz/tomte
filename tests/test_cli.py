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

"""Tests for `tomte/cli.py` shortcut commands.

Regression: format-code / check-code / check-security previously shelled
out to plain `tox -e <env>`, which under the slim `[tomte-extensions]`
overlay form fails because the lint envs live in tomte's bundled tox.ini
(merged in only by `tomte tox`). The fix routes them through
`tomte_tox.callback`. These tests pin that routing in place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from click.testing import CliRunner

from tomte.cli import check_code, check_security, format_code


def _capture_tomte_tox(monkeypatch: Any) -> List[Dict[str, Any]]:
    """Replace `tomte_tox.callback` with a recorder; return the call log."""
    calls: List[Dict[str, Any]] = []

    def _fake(
        repo_root: Path, show: bool, tox_args: Tuple[str, ...]
    ) -> None:
        calls.append({"repo_root": repo_root, "show": show, "tox_args": tox_args})

    monkeypatch.setattr("tomte.cli.tomte_tox.callback", _fake)
    return calls


def test_format_code_routes_through_tomte_tox(monkeypatch: Any) -> None:
    calls = _capture_tomte_tox(monkeypatch)
    result = CliRunner().invoke(format_code, [])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["show"] is False
    assert calls[0]["tox_args"] == ("-e", "isort", "-e", "black")


def test_check_code_routes_through_tomte_tox(monkeypatch: Any) -> None:
    calls = _capture_tomte_tox(monkeypatch)
    result = CliRunner().invoke(check_code, [])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["show"] is False
    assert calls[0]["tox_args"] == (
        "-p",
        "-e", "black-check",
        "-e", "isort-check",
        "-e", "flake8",
        "-e", "mypy",
        "-e", "pylint",
        "-e", "darglint",
    )


def test_check_security_routes_through_tomte_tox(monkeypatch: Any) -> None:
    calls = _capture_tomte_tox(monkeypatch)
    result = CliRunner().invoke(check_security, [])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["show"] is False
    assert calls[0]["tox_args"] == ("-p", "-e", "safety", "-e", "bandit")
