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

"""Tests for tomte's render-*-config and freeze-gitleaks helpers."""

import configparser
import json
from pathlib import Path
from unittest.mock import patch

from tomte import configs
from tomte.tools import freeze_gitleaks, render_isort_config, render_mypy_config


def test_render_isort_config_appends_known_keys(tmp_path):
    out = tmp_path / "isort.cfg"
    render_isort_config.main(
        output=str(out),
        known_first_party="autonomy",
        known_packages="packages",
        known_local_folder="tests",
    )
    parser = configparser.ConfigParser()
    parser.read(out)
    assert parser.has_section("isort")
    assert parser["isort"]["known_first_party"] == "autonomy"
    assert parser["isort"]["known_packages"] == "packages"
    assert parser["isort"]["known_local_folder"] == "tests"
    # Canonical settings still present
    assert parser["isort"]["profile"] == "black"


def test_render_isort_config_no_overrides(tmp_path):
    out = tmp_path / "isort.cfg"
    render_isort_config.main(output=str(out))
    parser = configparser.ConfigParser()
    parser.read(out)
    assert parser.has_section("isort")
    assert parser["isort"]["profile"] == "black"
    for key in ("known_first_party", "known_packages", "known_local_folder"):
        assert key not in parser["isort"]


def test_render_mypy_config_appends_overlay(tmp_path):
    overlay = tmp_path / "tox.ini"
    overlay.write_text(
        "[mypy-foobar.*]\nignore_missing_imports = True\n", encoding="utf-8"
    )
    out = tmp_path / "mypy.ini"
    render_mypy_config.main(output=str(out), append_from=str(overlay))
    parser = configparser.ConfigParser()
    parser.read(out)
    assert parser.has_section("mypy")
    assert parser["mypy"]["disallow_untyped_defs"] == "True"
    assert parser.has_section("mypy-foobar.*")
    assert parser["mypy-foobar.*"]["ignore_missing_imports"] == "True"


def test_render_mypy_config_no_overlay(tmp_path):
    """Without an overlay, the rendered mypy.ini equals tomte's canonical
    (base [mypy] block + the framework-level [mypy-<lib>] entries shipped
    in tomte/configs/mypy.ini). Repo-specific overrides come from the
    `--append-from` overlay applied by the [testenv:mypy] commands_pre.
    """
    out = tmp_path / "mypy.ini"
    render_mypy_config.main(output=str(out))
    parser = configparser.ConfigParser()
    parser.read(out)
    assert parser.has_section("mypy")
    canonical = configparser.ConfigParser()
    canonical.read(configs.MYPY_INI)
    rendered_overlays = sorted(s for s in parser.sections() if s.startswith("mypy-"))
    canonical_overlays = sorted(s for s in canonical.sections() if s.startswith("mypy-"))
    assert rendered_overlays == canonical_overlays


def test_freeze_gitleaks_emits_fingerprints(tmp_path):
    out = tmp_path / ".gitleaksignore"
    fake_findings = [
        {
            "Fingerprint": "abc123:foo.txt:RSA-PK:42",
            "Commit": "abc123",
            "File": "foo.txt",
            "RuleID": "RSA-PK",
            "StartLine": 42,
        },
        {
            "Fingerprint": "def456:bar.json:generic-api-key:7",
            "Commit": "def456",
            "File": "bar.json",
            "RuleID": "generic-api-key",
            "StartLine": 7,
        },
    ]

    def fake_run(*args, **kwargs):
        # Mimic gitleaks: write findings to the JSON report path passed via -r
        cmd = args[0]
        report_path = cmd[cmd.index("-r") + 1]
        Path(report_path).write_text(json.dumps(fake_findings))

        class _Result:
            returncode = 1
            stderr = ""

        return _Result()

    with patch("tomte.tools.freeze_gitleaks.shutil.which", return_value="/usr/bin/gitleaks"), patch(
        "tomte.tools.freeze_gitleaks.subprocess.run", side_effect=fake_run
    ):
        freeze_gitleaks.main(output=str(out))

    lines = out.read_text().strip().splitlines()
    assert lines == sorted(["abc123:foo.txt:RSA-PK:42", "def456:bar.json:generic-api-key:7"])


def test_freeze_gitleaks_no_findings_writes_empty(tmp_path):
    out = tmp_path / ".gitleaksignore"

    def fake_run(*args, **kwargs):
        cmd = args[0]
        report_path = cmd[cmd.index("-r") + 1]
        Path(report_path).write_text("[]")

        class _Result:
            returncode = 0
            stderr = ""

        return _Result()

    with patch("tomte.tools.freeze_gitleaks.shutil.which", return_value="/usr/bin/gitleaks"), patch(
        "tomte.tools.freeze_gitleaks.subprocess.run", side_effect=fake_run
    ):
        freeze_gitleaks.main(output=str(out))

    assert out.read_text() == ""


def test_freeze_gitleaks_missing_binary_raises(tmp_path):
    out = tmp_path / ".gitleaksignore"
    with patch("tomte.tools.freeze_gitleaks.shutil.which", return_value=None):
        try:
            freeze_gitleaks.main(output=str(out))
        except SystemExit as exc:
            assert "not found on PATH" in str(exc)
        else:
            raise AssertionError("expected SystemExit when gitleaks binary missing")


def test_freeze_gitleaks_empty_report_aborts(tmp_path):
    """Zero-byte report (gitleaks crashed mid-write) must NOT freeze an empty
    baseline silently — that would disable the .gitleaksignore on every
    subsequent run."""
    out = tmp_path / ".gitleaksignore"

    def fake_run(*args, **kwargs):
        cmd = args[0]
        report_path = cmd[cmd.index("-r") + 1]
        # Touch the file at zero bytes (simulating partial flush / disk full)
        Path(report_path).write_text("")

        class _Result:
            returncode = 0
            stderr = "gitleaks: I/O error after partial flush\n"

        return _Result()

    with patch("tomte.tools.freeze_gitleaks.shutil.which", return_value="/usr/bin/gitleaks"), patch(
        "tomte.tools.freeze_gitleaks.subprocess.run", side_effect=fake_run
    ):
        try:
            freeze_gitleaks.main(output=str(out))
        except SystemExit as exc:
            assert "0 bytes" in str(exc) or "empty" in str(exc)
        else:
            raise AssertionError("expected SystemExit on empty report")
    # The output must not have been written either way
    assert not out.exists() or out.read_text() == ""


def test_freeze_gitleaks_missing_report_aborts(tmp_path):
    """Vanished report file (e.g. tmp janitor deleted it mid-run) aborts.

    Note: in normal use `tempfile.NamedTemporaryFile(delete=False)` always
    leaves a zero-byte file in place; the empty-file branch above covers
    "subprocess never wrote to the report" cases. To exercise the
    truly-missing branch, simulate the file being unlinked between
    creation and the gate.
    """
    out = tmp_path / ".gitleaksignore"

    def fake_run(*args, **kwargs):
        cmd = args[0]
        report_path = cmd[cmd.index("-r") + 1]
        # Simulate something deleting the temp file between subprocess
        # creation and the post-run check (e.g. an aggressive tmp janitor,
        # or a CI step that wipes /tmp).
        Path(report_path).unlink(missing_ok=True)

        class _Result:
            returncode = 1
            stderr = "gitleaks: SIGSEGV during scan\n"

        return _Result()

    with patch("tomte.tools.freeze_gitleaks.shutil.which", return_value="/usr/bin/gitleaks"), patch(
        "tomte.tools.freeze_gitleaks.subprocess.run", side_effect=fake_run
    ):
        try:
            freeze_gitleaks.main(output=str(out))
        except SystemExit as exc:
            assert "wrote no report" in str(exc)
        else:
            raise AssertionError("expected SystemExit on missing report")
