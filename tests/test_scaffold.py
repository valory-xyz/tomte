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

from click.testing import CliRunner

from tomte.scaffold import GENERATED_MARKER, scaffold


_AGENT_TOX = textwrap.dedent(
    """
    [tomte-scaffold]
    open_autonomy_version = 0.21.19
    open_aea_version = 2.2.1
    packages_paths = packages/valory
    service_specific_packages = packages/valory/skills/foo
    pytest_targets = packages/valory/skills/foo/tests
    service_public_id = valory/foo
    known_first_party = autonomy
    """
).lstrip()

_LIBRARY_TOX = textwrap.dedent(
    """
    [tomte-scaffold]
    template_kind = library
    lint_targets = mech_client/
    known_first_party = mech_client
    """
).lstrip()


def _write_tox_ini(repo_root: Path, body: str = _AGENT_TOX) -> None:
    (repo_root / "tox.ini").write_text(body, encoding="utf-8")


def _placeholders_outside_comments(rendered: str) -> list:
    body = "\n".join(
        line for line in rendered.splitlines() if not line.lstrip().startswith(";")
    )
    return re.findall(r"\$[A-Z_][A-Z_0-9]*", body)


def test_scaffold_dry_run_emits_generated_marker(tmp_path):
    """`tomte scaffold tox --dry-run` writes nothing and prints a rendered tox.ini."""
    _write_tox_ini(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        scaffold, ["tox", "--repo-root", str(tmp_path), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.startswith(GENERATED_MARKER)
    # dry-run should NOT have overwritten the input
    assert "[tomte-scaffold]" in (tmp_path / "tox.ini").read_text(encoding="utf-8")
    assert "[testenv:bandit]" not in (tmp_path / "tox.ini").read_text(encoding="utf-8")


def test_scaffold_writes_file_and_resolves_all_placeholders(tmp_path):
    """A real scaffold writes tox.ini with no unresolved $VAR placeholders."""
    _write_tox_ini(tmp_path)
    runner = CliRunner()
    # Force needed because the input tox.ini doesn't yet carry the marker.
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert result.exit_code == 0, result.output

    rendered = (tmp_path / "tox.ini").read_text(encoding="utf-8")
    assert rendered.startswith(GENERATED_MARKER), "missing canonical marker line"
    # The [tomte-scaffold] section must survive
    assert "[tomte-scaffold]" in rendered
    assert "service_public_id = valory/foo" in rendered
    assert _placeholders_outside_comments(rendered) == []


def test_scaffold_refuses_overwriting_handwritten_tox_ini(tmp_path):
    """Without --force, scaffold refuses to clobber a non-canonical tox.ini."""
    (tmp_path / "tox.ini").write_text(
        _AGENT_TOX + "\n[tox]\nenvlist = py310\n", encoding="utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert result.exit_code != 0
    assert "does not look like a previously-generated scaffold" in result.output


def test_scaffold_overwrites_previous_scaffold_without_force(tmp_path):
    """A previously-generated scaffold (carries the marker) is safe to overwrite."""
    _write_tox_ini(tmp_path)
    runner = CliRunner()
    first = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert first.exit_code == 0
    # Second invocation: no --force; allowed because tox.ini now has the marker.
    second = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert second.exit_code == 0, second.output


def test_scaffold_errors_on_missing_required_key(tmp_path):
    """Missing required keys produce a useful UsageError, not a placeholder leak."""
    _write_tox_ini(
        tmp_path,
        textwrap.dedent(
            """
            [tomte-scaffold]
            open_autonomy_version = 0.21.19
            open_aea_version = 2.2.1
            packages_paths = packages/valory
            """
        ).lstrip(),
    )
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert result.exit_code != 0
    assert "missing required keys" in result.output
    assert "service_specific_packages" in result.output


def test_scaffold_errors_when_no_scaffold_section(tmp_path):
    """A tox.ini with no `[tomte-scaffold]` section yields a clear error."""
    (tmp_path / "tox.ini").write_text("[tox]\nenvlist = py310\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert result.exit_code != 0
    assert "[tomte-scaffold]" in result.output


def test_scaffold_errors_when_no_tox_ini(tmp_path):
    """Missing tox.ini error directs the user to bootstrap a stub."""
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path)])
    assert result.exit_code != 0
    assert "stub tox.ini" in result.output


def test_scaffold_library_mode_renders(tmp_path):
    """`template_kind = "library"` renders the library template, not the agent one."""
    _write_tox_ini(tmp_path, _LIBRARY_TOX)
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert result.exit_code == 0, result.output

    rendered = (tmp_path / "tox.ini").read_text(encoding="utf-8")
    assert rendered.startswith(GENERATED_MARKER)
    assert "SERVICE_SPECIFIC_PACKAGES" not in rendered
    assert "autonomy init" not in rendered
    assert "py{3.10,3.11,3.12,3.13,3.14}" not in rendered
    assert "[testenv:check-hash]" not in rendered
    assert "mech_client/" in rendered
    assert _placeholders_outside_comments(rendered) == []


def test_scaffold_library_mode_missing_lint_targets_errors(tmp_path):
    """Library mode requires `lint_targets`; missing it should error clearly."""
    _write_tox_ini(
        tmp_path,
        textwrap.dedent(
            """
            [tomte-scaffold]
            template_kind = library
            known_first_party = mech_client
            """
        ).lstrip(),
    )
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert result.exit_code != 0
    assert "lint_targets" in result.output
    assert "template_kind='library'" in result.output


def test_scaffold_unknown_template_kind_errors(tmp_path):
    """An invalid `template_kind` value is rejected up-front."""
    _write_tox_ini(
        tmp_path,
        textwrap.dedent(
            """
            [tomte-scaffold]
            template_kind = framework
            """
        ).lstrip(),
    )
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert result.exit_code != 0
    assert "template_kind" in result.output


def test_scaffold_pylint_extras_default_to_no_flags(tmp_path):
    """Without extra_pylint_* keys, pylint env carries no extension flags."""
    _write_tox_ini(tmp_path)
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert result.exit_code == 0, result.output

    rendered = (tmp_path / "tox.ini").read_text(encoding="utf-8")
    pylint_block = _extract_section(rendered, "[testenv:pylint]")
    assert "--ignored-modules=" not in pylint_block, pylint_block
    assert "--disable=" not in pylint_block, pylint_block


def test_scaffold_pylint_extras_render_into_cli_flags(tmp_path):
    """When extra_pylint_* keys are set, they appear as full CLI flags."""
    _write_tox_ini(
        tmp_path,
        textwrap.dedent(
            """
            [tomte-scaffold]
            open_autonomy_version = 0.21.19
            open_aea_version = 2.2.1
            packages_paths = packages/valory
            service_specific_packages = packages/valory/skills/foo
            pytest_targets = packages/valory/skills/foo/tests
            service_public_id = valory/foo
            known_first_party = autonomy
            extra_pylint_ignored_modules = web3,pandas,numpy
            extra_pylint_disables = C0111,R0902
            """
        ).lstrip(),
    )
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert result.exit_code == 0, result.output
    pylint_block = _extract_section((tmp_path / "tox.ini").read_text(), "[testenv:pylint]")
    assert "--ignored-modules=web3,pandas,numpy" in pylint_block
    assert "--disable=C0111,R0902" in pylint_block


def test_scaffold_tomte_dep_pin_default_is_pypi_version(tmp_path):
    """tomte_dep_pin defaults to `==<tomte_version>` (PyPI form)."""
    _write_tox_ini(tmp_path)
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert result.exit_code == 0, result.output
    rendered = (tmp_path / "tox.ini").read_text()
    assert "tomte[bandit]==" in rendered, "default pin should be PyPI ==X.Y.Z form"


def test_scaffold_tomte_dep_pin_overridable(tmp_path):
    """When tomte_dep_pin is overridden (e.g. git URL), the override takes effect."""
    _write_tox_ini(
        tmp_path,
        textwrap.dedent(
            """
            [tomte-scaffold]
            open_autonomy_version = 0.21.19
            open_aea_version = 2.2.1
            packages_paths = packages/valory
            service_specific_packages = packages/valory/skills/foo
            pytest_targets = packages/valory/skills/foo/tests
            service_public_id = valory/foo
            known_first_party = autonomy
            tomte_dep_pin = @ git+https://github.com/valory-xyz/tomte.git@deadbeef
            """
        ).lstrip(),
    )
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert result.exit_code == 0, result.output
    rendered = (tmp_path / "tox.ini").read_text()
    assert "tomte[bandit]@ git+https://github.com/valory-xyz/tomte.git@deadbeef" in rendered


def test_scaffold_extra_mypy_overrides_appended(tmp_path):
    """`extra_mypy_overrides` (multi-line ini text) appears verbatim at the bottom."""
    _write_tox_ini(
        tmp_path,
        textwrap.dedent(
            """
            [tomte-scaffold]
            open_autonomy_version = 0.21.19
            open_aea_version = 2.2.1
            packages_paths = packages/valory
            service_specific_packages = packages/valory/skills/foo
            pytest_targets = packages/valory/skills/foo/tests
            service_public_id = valory/foo
            known_first_party = autonomy
            extra_mypy_overrides =
                [mypy-pandas.*]
                ignore_missing_imports = True

                [mypy-numpy.*]
                ignore_missing_imports = True
            """
        ).lstrip(),
    )
    runner = CliRunner()
    result = runner.invoke(scaffold, ["tox", "--repo-root", str(tmp_path), "--force"])
    assert result.exit_code == 0, result.output
    rendered = (tmp_path / "tox.ini").read_text()
    assert "[mypy-pandas.*]" in rendered
    assert "[mypy-numpy.*]" in rendered


def _extract_section(text: str, header: str) -> str:
    out = []
    in_section = False
    for line in text.splitlines():
        if line.strip() == header:
            in_section = True
            out.append(line)
            continue
        if in_section and line.startswith("[") and line.strip() != header:
            break
        if in_section:
            out.append(line)
    return "\n".join(out)
