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
`tomte_tox.callback`. These tests pin that routing in place plus the
exit-code propagation contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from click.testing import CliRunner

from tomte.cli import _run_canonical_tox, check_code, check_security, format_code
from tomte.tools.tox_runtime import tomte_tox


def _capture_tomte_tox(monkeypatch: Any) -> List[Dict[str, Any]]:
    """Replace `tomte_tox.callback` with a recorder; return the call log."""
    calls: List[Dict[str, Any]] = []

    def _fake(
        repo_root: Path, show: bool, tox_args: Tuple[str, ...]
    ) -> None:
        calls.append({"repo_root": repo_root, "show": show, "tox_args": tox_args})

    monkeypatch.setattr("tomte.cli.tomte_tox.callback", _fake)
    return calls


# --------------------------------------------------------------------------
# Routing — verify each shortcut hits tomte_tox.callback with the right args
# --------------------------------------------------------------------------


def test_format_code_routes_through_tomte_tox(monkeypatch: Any) -> None:
    calls = _capture_tomte_tox(monkeypatch)
    result = CliRunner().invoke(format_code, [])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["repo_root"] == Path.cwd()
    assert calls[0]["show"] is False
    assert calls[0]["tox_args"] == ("-e", "isort", "-e", "black")


def test_check_code_routes_through_tomte_tox(monkeypatch: Any) -> None:
    calls = _capture_tomte_tox(monkeypatch)
    result = CliRunner().invoke(check_code, [])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["repo_root"] == Path.cwd()
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
    assert calls[0]["repo_root"] == Path.cwd()
    assert calls[0]["show"] is False
    assert calls[0]["tox_args"] == ("-p", "-e", "safety", "-e", "bandit")


# --------------------------------------------------------------------------
# Exit-code propagation — `tomte_tox.callback` ends with `sys.exit(returncode)`
# so a non-zero from the inner tox run must reach the user (CI contract).
# --------------------------------------------------------------------------


@pytest.mark.parametrize("command", [format_code, check_code, check_security])
def test_shortcut_propagates_non_zero_exit(command: Any, monkeypatch: Any) -> None:
    """Non-zero `SystemExit` from `tomte_tox.callback` bubbles up to the runner."""
    def _fake(**_kwargs: Any) -> None:
        raise SystemExit(2)
    monkeypatch.setattr("tomte.cli.tomte_tox.callback", _fake)
    assert CliRunner().invoke(command, []).exit_code == 2


# --------------------------------------------------------------------------
# Direct `_run_canonical_tox` contract — pins the helper independent of the
# command-level wiring, so a future refactor of one doesn't silently move
# the other.
# --------------------------------------------------------------------------


def test_run_canonical_tox_passes_args_unchanged(monkeypatch: Any) -> None:
    """Helper forwards `args` verbatim as the `tox_args` tuple."""
    calls = _capture_tomte_tox(monkeypatch)
    _run_canonical_tox(("-p", "-e", "black-check"))
    assert len(calls) == 1
    assert calls[0]["repo_root"] == Path.cwd()
    assert calls[0]["show"] is False
    assert calls[0]["tox_args"] == ("-p", "-e", "black-check")


# --------------------------------------------------------------------------
# Integration — the slim-overlay regression originates inside
# `tomte_tox.callback` (canonical-config render). Routing-shape tests above
# would still pass if the rendering logic in `tox_runtime.py` were reverted.
# This test exercises the real callback against a synthetic slim-overlay
# repo and asserts the rendered `.tomte-tox.ini` actually defines the lint
# envs the shortcut commands target.
# --------------------------------------------------------------------------


_PYPROJECT_SLIM = """\
[project]
name = "fakerepo"
version = "0.1.0"
dependencies = [
    "open-autonomy==0.21.19",
    "open-aea-ledger-ethereum==2.2.1",
]

[tool.tomte]
"""


def _write_slim_repo(repo_root: Path) -> None:
    (repo_root / "pyproject.toml").write_text(_PYPROJECT_SLIM, encoding="utf-8")
    pkg_dir = repo_root / "packages" / "valory" / "skills" / "alpha"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (repo_root / "packages" / "packages.json").write_text(
        json.dumps({"dev": {"skill/valory/alpha/0.1.0": "bafy_alpha"}, "third_party": {}}),
        encoding="utf-8",
    )


def test_canonical_render_defines_envs_targeted_by_shortcuts(tmp_path: Path) -> None:
    """`tomte_tox.callback(show=True)` renders all envs `tomte check-code` targets.

    Regression pin for the original break: the shortcut commands referenced
    `black-check`, `isort-check`, `flake8`, `mypy`, `pylint`, `darglint`,
    `safety`, `bandit`, `isort`, `black` — none of which exist in the slim
    `[tomte-extensions]` overlay form. Routing them through `tomte_tox.callback`
    is only the fix if the merged render actually defines those envs. If the
    canonical `tox.ini` template ever drops one, the corresponding shortcut
    silently breaks again. This pins the contract.
    """
    _write_slim_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(tomte_tox, ["--repo-root", str(tmp_path), "--show"])
    assert result.exit_code == 0, result.output
    out = result.output
    for env in (
        "black-check", "isort-check", "flake8", "mypy", "pylint", "darglint",
        "safety", "bandit", "isort", "black",
    ):
        assert f"[testenv:{env}]" in out, f"canonical render missing [testenv:{env}]"
