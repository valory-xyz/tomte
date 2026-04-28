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

"""Release gate for `tomte scaffold tox`: render must succeed end-to-end."""

import re
import textwrap
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from tomte.scaffold import GENERATED_MARKER, scaffold


_MINIMAL_PYPROJECT = textwrap.dedent(
    """
    [project]
    name = "smoke"
    version = "0.0.0"

    [tool.tomte.scaffold]
    open_autonomy_version = "0.21.19"
    open_aea_version = "2.2.1"
    packages_paths = "packages/valory"
    service_specific_packages = "packages/valory/skills/foo"
    pytest_targets = "packages/valory/skills/foo/tests"
    service_public_id = "valory/foo"
    known_first_party = "autonomy"
    """
).strip()


def _write_pyproject(repo_root: Path, body: str = _MINIMAL_PYPROJECT) -> None:
    (repo_root / "pyproject.toml").write_text(body, encoding="utf-8")


def test_scaffold_dry_run_emits_generated_marker(tmp_path):
    """`tomte scaffold tox --dry-run` writes nothing and prints a rendered tox.ini."""
    _write_pyproject(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        scaffold, ["tox", "--repo-root", str(tmp_path), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.startswith(GENERATED_MARKER)
    assert not (tmp_path / "tox.ini").exists(), "dry-run must not write the file"


def test_scaffold_writes_file_and_resolves_all_placeholders(tmp_path):
    """A real scaffold writes tox.ini with no unresolved $VAR placeholders."""
    _write_pyproject(tmp_path)
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert result.exit_code == 0, result.output

    rendered = (tmp_path / "tox.ini").read_text(encoding="utf-8")
    assert rendered.startswith(GENERATED_MARKER), "missing canonical marker line"

    # The rendered file may contain literal $VAR strings inside the doc-comment
    # block (those use $$VAR in the template and survive verbatim) but must NOT
    # contain any unresolved placeholder OUTSIDE the comment block.
    body = "\n".join(
        line for line in rendered.splitlines() if not line.lstrip().startswith(";")
    )
    unresolved = re.findall(r"\$[A-Z_][A-Z_0-9]*", body)
    assert not unresolved, f"unresolved placeholders in rendered tox.ini: {unresolved}"


def test_scaffold_refuses_overwriting_handwritten_tox_ini(tmp_path):
    """Without --force, scaffold refuses to clobber a non-canonical tox.ini."""
    _write_pyproject(tmp_path)
    (tmp_path / "tox.ini").write_text("[tox]\nenvlist = py310\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert result.exit_code != 0
    assert "does not look like a previously-generated scaffold" in result.output


def test_scaffold_overwrites_previous_scaffold_without_force(tmp_path):
    """A previously-generated scaffold (carries the marker) is safe to overwrite."""
    _write_pyproject(tmp_path)
    runner = CliRunner()
    first = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert first.exit_code == 0
    second = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert second.exit_code == 0, second.output


def test_scaffold_errors_on_missing_required_key(tmp_path):
    """Missing required keys produce a useful UsageError, not a placeholder leak."""
    _write_pyproject(
        tmp_path,
        textwrap.dedent(
            """
            [project]
            name = "smoke"
            version = "0.0.0"

            [tool.tomte.scaffold]
            open_autonomy_version = "0.21.19"
            open_aea_version = "2.2.1"
            packages_paths = "packages/valory"
            # service_specific_packages, pytest_targets, service_public_id,
            # known_first_party intentionally omitted
            """
        ).strip(),
    )
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert result.exit_code != 0
    assert "missing required keys" in result.output
    assert "service_specific_packages" in result.output


def test_scaffold_errors_when_no_scaffold_block(tmp_path):
    """An empty [tool.tomte.scaffold] block yields a clear error."""
    _write_pyproject(
        tmp_path,
        textwrap.dedent(
            """
            [project]
            name = "smoke"
            version = "0.0.0"
            """
        ).strip(),
    )
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert result.exit_code != 0
    assert "[tool.tomte.scaffold]" in result.output


_LIBRARY_PYPROJECT = textwrap.dedent(
    """
    [project]
    name = "lib-smoke"
    version = "0.0.0"

    [tool.tomte.scaffold]
    template_kind = "library"
    lint_targets = "mech_client/"
    known_first_party = "mech_client"
    """
).strip()


def test_scaffold_library_mode_renders(tmp_path):
    """`template_kind = "library"` renders the library template, not the agent one."""
    _write_pyproject(tmp_path, _LIBRARY_PYPROJECT)
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert result.exit_code == 0, result.output

    rendered = (tmp_path / "tox.ini").read_text(encoding="utf-8")
    assert rendered.startswith(GENERATED_MARKER)
    # Library template MUST NOT carry agent-shaped concepts:
    assert "SERVICE_SPECIFIC_PACKAGES" not in rendered, (
        "library template leaked agent-only var SERVICE_SPECIFIC_PACKAGES"
    )
    assert "autonomy init" not in rendered, (
        "library template leaked autonomy bootstrap"
    )
    assert "py{3.10,3.11,3.12,3.13,3.14}" not in rendered, (
        "library template leaked agent factor matrix"
    )
    assert "[testenv:check-hash]" not in rendered, (
        "library template leaked agent autonomy-check env"
    )
    # Library template MUST carry the lint-target substitution:
    assert "mech_client/" in rendered
    # Body has no unresolved placeholders outside the comment block.
    body = "\n".join(
        line for line in rendered.splitlines() if not line.lstrip().startswith(";")
    )
    import re
    unresolved = re.findall(r"\$[A-Z_][A-Z_0-9]*", body)
    assert not unresolved, f"unresolved placeholders: {unresolved}"


def test_scaffold_library_mode_missing_lint_targets_errors(tmp_path):
    """Library mode requires `lint_targets`; missing it should error clearly."""
    _write_pyproject(
        tmp_path,
        textwrap.dedent(
            """
            [project]
            name = "lib-smoke"
            version = "0.0.0"

            [tool.tomte.scaffold]
            template_kind = "library"
            known_first_party = "mech_client"
            """
        ).strip(),
    )
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert result.exit_code != 0
    assert "lint_targets" in result.output
    assert "template_kind='library'" in result.output


def test_scaffold_unknown_template_kind_errors(tmp_path):
    """An invalid `template_kind` value is rejected up-front."""
    _write_pyproject(
        tmp_path,
        textwrap.dedent(
            """
            [project]
            name = "smoke"
            version = "0.0.0"

            [tool.tomte.scaffold]
            template_kind = "framework"
            """
        ).strip(),
    )
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert result.exit_code != 0
    assert "template_kind" in result.output
