"""Tests for `tomte export-safety-requirements`."""

from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from tomte.cli import cli
from tomte.tools.export_safety_requirements import export


_UV_LOCK = """\
version = 1

[[package]]
name = "fakerepo"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "workspace-member"
version = "0.1.0"
source = { virtual = "member" }

[[package]]
name = "urllib3"
version = "2.6.3"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "google-api-core"
version = "2.25.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "google-api-core"
version = "2.24.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "tomte"
version = "0.7.3"
source = { git = "https://github.com/valory-xyz/tomte.git?rev=v0.7.3" }
"""

_POETRY_LOCK = """\
[[package]]
name = "filelock"
version = "3.20.0"

[[package]]
name = "localpkg"
version = "0.1.0"

[package.source]
type = "directory"
url = "localpkg"
"""


def test_export_pins_released_packages_from_uv_lock(tmp_path: Path) -> None:
    """Local sources are the repo itself; every other version is pinned."""
    (tmp_path / "uv.lock").write_text(_UV_LOCK, encoding="utf-8")
    assert export(tmp_path) == (
        "google-api-core==2.24.0\n"
        "google-api-core==2.25.0\n"
        "tomte==0.7.3\n"
        "urllib3==2.6.3\n",
        ["tomte"],
    )


def test_export_reads_poetry_lock(tmp_path: Path) -> None:
    (tmp_path / "poetry.lock").write_text(_POETRY_LOCK, encoding="utf-8")
    assert export(tmp_path) == ("filelock==3.20.0\n", [])


def test_export_prefers_uv_lock(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text(_UV_LOCK, encoding="utf-8")
    (tmp_path / "poetry.lock").write_text(_POETRY_LOCK, encoding="utf-8")
    assert "filelock" not in export(tmp_path)[0]


def test_export_fails_without_a_lock(tmp_path: Path) -> None:
    with pytest.raises(click.ClickException, match="nothing to scan"):
        export(tmp_path)


def test_export_fails_on_a_malformed_lock(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("[[package]\n", encoding="utf-8")
    with pytest.raises(click.ClickException, match="Cannot read"):
        export(tmp_path)


def test_command_writes_the_pins_and_names_unpublished_sources(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text(_UV_LOCK, encoding="utf-8")
    output = tmp_path / "out" / "requirements.txt"
    output.parent.mkdir()
    result = CliRunner().invoke(
        cli,
        ["export-safety-requirements", "--output-path", str(output), "--repo-root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "urllib3==2.6.3\n" in output.read_text(encoding="utf-8")
    assert "PyPI release of the same version instead: tomte" in result.output


def test_command_fails_without_a_lock(tmp_path: Path) -> None:
    output = tmp_path / "requirements.txt"
    result = CliRunner().invoke(
        cli,
        ["export-safety-requirements", "--output-path", str(output), "--repo-root", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "nothing to scan" in result.output
    assert not output.exists()
