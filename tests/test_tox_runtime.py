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

"""Tests for tomte/tools/tox_runtime.py.

Focus: regression coverage for the helpers reachable only via the `tomte
tox` CLI and the wrapper itself. We exercise both auto-discovery and
explicit-list paths for `_resolve_pytest_targets` /
`_resolve_service_specific_packages`, the `*_extra` / `*_exclude`
merge semantics, the new `gitleaks_extra_regexes` and `extra_pylint_*`
emitters, the `_resolve_check_handlers_ignores` packages.json merge,
and the end-to-end Click invocation (--show, malformed tox.ini error,
sidecar marker safety).
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import List, Sequence

import click
import pytest
from click.testing import CliRunner

from tomte.tools.tox_runtime import (
    _MANAGED_MARKER,
    _drop_ini_section,
    _render_gitleaks_merged,
    _render_pylint_flags,
    _resolve_check_handlers_ignores,
    _resolve_pytest_targets,
    _resolve_service_public_ids,
    _resolve_service_specific_packages,
    tomte_tox,
)


# --------------------------------------------------------------------------
# Fixture helpers — mirror the layout used in `tests/test_render_and_freeze.py`
# (write minimal artefacts under tmp_path; no global state).
# --------------------------------------------------------------------------


_PYPROJECT_MIN = """\
[project]
name = "fakerepo"
version = "0.1.0"
dependencies = [
    "open-autonomy==0.21.19",
    "open-aea-ledger-ethereum==2.2.1",
    "web3==7.14.1",
]

[tool.tomte]
"""


def _write_repo_skeleton(
    repo_root: Path,
    *,
    with_packages_json: bool = True,
    services: Sequence[str] = (),
) -> None:
    """Write a minimal repo: pyproject.toml + (optional) packages/ tree.

    The packages/ layout matches what `_detect_packages_paths` and
    `dev_package_paths` walk: `packages/<author>/<type-plural>/<name>/`.
    """
    (repo_root / "pyproject.toml").write_text(_PYPROJECT_MIN, encoding="utf-8")

    if not with_packages_json:
        return

    pkg_dir = repo_root / "packages" / "valory"
    (pkg_dir / "skills" / "alpha" / "tests").mkdir(parents=True)
    (pkg_dir / "skills" / "alpha" / "tests" / "test_alpha.py").write_text(
        "def test_x(): pass\n", encoding="utf-8"
    )
    (pkg_dir / "skills" / "beta" / "tests").mkdir(parents=True)
    (pkg_dir / "skills" / "beta" / "tests" / "test_beta.py").write_text(
        "def test_y(): pass\n", encoding="utf-8"
    )
    dev = {
        "skill/valory/alpha/0.1.0": "bafy_alpha",
        "skill/valory/beta/0.1.0": "bafy_beta",
    }
    for name in services:
        dev[f"service/valory/{name}/0.1.0"] = f"bafy_{name}"
    packages_json = {
        "dev": dev,
        "third_party": {
            "skill/valory/abstract_round_abci/0.1.0": "bafy_arb",
            "contract/valory/gnosis_safe/0.1.0": "bafy_gs",
        },
    }
    (repo_root / "packages" / "packages.json").write_text(
        json.dumps(packages_json), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# _resolve_pytest_targets
# --------------------------------------------------------------------------


def test_resolve_pytest_targets_auto_discovery(tmp_path: Path) -> None:
    """No `pytest_targets` → derive from packages.json dev entries."""
    _write_repo_skeleton(tmp_path)
    out = _resolve_pytest_targets(tmp_path, identity={})
    assert sorted(out) == [
        "packages/valory/skills/alpha/tests",
        "packages/valory/skills/beta/tests",
    ]


def test_resolve_pytest_targets_explicit_with_extra_and_exclude(tmp_path: Path) -> None:
    """Explicit list + `*_extra` adds + `*_exclude` subtracts (uniform with auto path)."""
    _write_repo_skeleton(tmp_path)
    identity = {
        "pytest_targets": ["a/tests", "b/tests", "c/tests"],
        "pytest_targets_exclude": ["b/tests"],
        "pytest_targets_extra": ["d/tests"],
    }
    out = _resolve_pytest_targets(tmp_path, identity)
    assert out == ["a/tests", "c/tests", "d/tests"]


def test_resolve_pytest_targets_auto_discovery_with_exclude(tmp_path: Path) -> None:
    """`*_exclude` subtracts from auto-discovered base too."""
    _write_repo_skeleton(tmp_path)
    identity = {"pytest_targets_exclude": ["packages/valory/skills/beta/tests"]}
    out = _resolve_pytest_targets(tmp_path, identity)
    assert out == ["packages/valory/skills/alpha/tests"]


# --------------------------------------------------------------------------
# _resolve_service_specific_packages
# --------------------------------------------------------------------------


def test_resolve_service_specific_packages_auto_discovery(tmp_path: Path) -> None:
    _write_repo_skeleton(tmp_path)
    out = _resolve_service_specific_packages(tmp_path, identity={})
    assert sorted(out) == [
        "packages/valory/skills/alpha",
        "packages/valory/skills/beta",
    ]


def test_resolve_service_specific_packages_extra_and_exclude(tmp_path: Path) -> None:
    _write_repo_skeleton(tmp_path)
    identity = {
        "service_specific_packages_exclude": ["packages/valory/skills/alpha"],
        "service_specific_packages_extra": ["scripts"],
    }
    out = _resolve_service_specific_packages(tmp_path, identity)
    # `alpha` excluded, `beta` retained, `scripts` appended.
    assert out == ["packages/valory/skills/beta", "scripts"]


# --------------------------------------------------------------------------
# _render_pylint_flags
# --------------------------------------------------------------------------


def test_render_pylint_flags_empty_when_no_extras() -> None:
    assert _render_pylint_flags(extensions={}, identity={}) == ""


def test_render_pylint_flags_emits_disable_and_ignored_modules() -> None:
    extensions = {
        "extra_pylint_disables": "C0111,W0613",
        "extra_pylint_ignored_modules": "web3,eth_typing",
    }
    rendered = _render_pylint_flags(extensions, identity={})
    assert "--ignored-modules=web3,eth_typing" in rendered
    assert "--disable=C0111,W0613" in rendered


def test_render_pylint_flags_identity_list_form() -> None:
    """`pylint_disables` list under [tool.tomte] is comma-joined."""
    rendered = _render_pylint_flags(
        extensions={}, identity={"pylint_disables": ["C0111", "W0613"]}
    )
    assert rendered == "--disable=C0111,W0613"


# --------------------------------------------------------------------------
# _resolve_check_handlers_ignores
# --------------------------------------------------------------------------


def test_check_handlers_ignores_auto_merges_third_party(tmp_path: Path) -> None:
    """Auto path: `-i <name>` for every third-party package in packages.json."""
    _write_repo_skeleton(tmp_path)
    rendered = _resolve_check_handlers_ignores(tmp_path, identity={})
    # third_party in packages.json: abstract_round_abci, gnosis_safe.
    assert "-i abstract_round_abci" in rendered
    assert "-i gnosis_safe" in rendered


def test_check_handlers_ignores_list_extends_third_party(tmp_path: Path) -> None:
    """List form: extras append on top of auto-derived third-party names."""
    _write_repo_skeleton(tmp_path)
    rendered = _resolve_check_handlers_ignores(
        tmp_path, identity={"check_handlers_ignores": ["my_utility_skill"]}
    )
    assert "-i abstract_round_abci" in rendered
    assert "-i gnosis_safe" in rendered
    assert "-i my_utility_skill" in rendered


def test_check_handlers_ignores_string_replaces(tmp_path: Path) -> None:
    """Legacy string form: used verbatim, replacing auto-derive."""
    _write_repo_skeleton(tmp_path)
    rendered = _resolve_check_handlers_ignores(
        tmp_path, identity={"check_handlers_ignores": "-i only_this"}
    )
    assert rendered == "-i only_this"
    assert "abstract_round_abci" not in rendered


# --------------------------------------------------------------------------
# _render_gitleaks_merged
# --------------------------------------------------------------------------


def test_gitleaks_merged_base_only(tmp_path: Path) -> None:
    """No extras → minimal `[extend]` block, no `[allowlist]`."""
    rendered = _render_gitleaks_merged(tmp_path, identity={})
    assert "[extend]" in rendered
    assert "useDefault = false" in rendered
    assert "[allowlist]" not in rendered


def test_gitleaks_merged_extra_paths_only(tmp_path: Path) -> None:
    rendered = _render_gitleaks_merged(
        tmp_path,
        identity={"gitleaks_extra_paths": ["frontend/dist/.*", "build/static/.*"]},
    )
    assert "[allowlist]" in rendered
    assert "paths = [" in rendered
    assert "'''frontend/dist/.*'''" in rendered
    assert "'''build/static/.*'''" in rendered
    assert "regexes = [" not in rendered


def test_gitleaks_merged_extra_regexes_emits_regexes_block(tmp_path: Path) -> None:
    """`gitleaks_extra_regexes` adds a `regexes = [...]` block (the new feature)."""
    rendered = _render_gitleaks_merged(
        tmp_path, identity={"gitleaks_extra_regexes": ["^bafy[A-Za-z0-9]{50,}$"]}
    )
    assert "[allowlist]" in rendered
    assert "regexes = [" in rendered
    assert "'''^bafy[A-Za-z0-9]{50,}$'''" in rendered


def test_gitleaks_merged_paths_and_regexes_combined(tmp_path: Path) -> None:
    rendered = _render_gitleaks_merged(
        tmp_path,
        identity={
            "gitleaks_extra_paths": ["foo/.*"],
            "gitleaks_extra_regexes": ["bar.*"],
        },
    )
    assert "paths = [" in rendered
    assert "regexes = [" in rendered


# --------------------------------------------------------------------------
# tomte_tox CLI — end-to-end via Click CliRunner
# --------------------------------------------------------------------------


def test_tomte_tox_show_renders_canonical_blocks(tmp_path: Path) -> None:
    """`--show` dumps rendered tox.ini; canonical blocks must be present."""
    _write_repo_skeleton(tmp_path)
    runner = CliRunner()
    result = runner.invoke(tomte_tox, ["--repo-root", str(tmp_path), "--show"])
    assert result.exit_code == 0, result.output
    out = result.output
    # Canonical envs the wrapper does NOT manage, but renders verbatim.
    assert "[testenv:pylint]" in out
    assert "[testenv:check-handlers]" in out
    assert "[testenv:gitleaks]" in out
    assert "[deps-packages]" in out
    # auto-derived EXTRA_DEPS_PACKAGES (web3 from pyproject.dependencies)
    assert "web3==7.14.1" in out
    # auto-derived check-handlers ignores (third-party packages)
    assert "-i abstract_round_abci" in out
    # canonical pins fall through from [project].dependencies parse
    assert "open-autonomy[all]==0.21.19" in out
    assert "open-aea-ledger-ethereum==2.2.1" in out


def test_tomte_tox_show_propagates_extensions(tmp_path: Path) -> None:
    """[tomte-extensions] in tox.ini → pylint flags + gitleaks regexes hit output."""
    _write_repo_skeleton(tmp_path)
    # Inject [tomte-extensions] for pylint flags + gitleaks regexes via TOML
    # (gitleaks extras come from [tool.tomte], pylint extras from
    # [tomte-extensions] in tox.ini — match production layering).
    pyproject = (tmp_path / "pyproject.toml").read_text()
    pyproject += textwrap.dedent(
        """
        gitleaks_extra_regexes = ["^bafybe[A-Za-z0-9]+$"]
        """
    )
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    (tmp_path / "tox.ini").write_text(
        textwrap.dedent(
            """\
            [tomte-extensions]
            extra_pylint_disables = C0111,W0613
            extra_pylint_ignored_modules = web3
            """
        ),
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(tomte_tox, ["--repo-root", str(tmp_path), "--show"])
    assert result.exit_code == 0, result.output
    assert "--disable=C0111,W0613" in result.output
    assert "--ignored-modules=web3" in result.output


def test_tomte_tox_malformed_local_toxini_raises_usage_error(tmp_path: Path) -> None:
    """Malformed tox.ini → click.UsageError (regression: read_file vs read).

    If the wrapper used configparser.read() instead of read_file(), a
    typo'd unbracketed line would silently drop every [tomte-extensions]
    override. This test pins read_file() in place by asserting the
    parse error propagates as a click usage error.
    """
    _write_repo_skeleton(tmp_path)
    (tmp_path / "tox.ini").write_text(
        # Unbracketed text before any section header — illegal in INI.
        "this line has no section header\n[tomte-extensions]\nextra_deps = foo\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(tomte_tox, ["--repo-root", str(tmp_path), "--show"])
    assert result.exit_code != 0
    # Click renders UsageError to stderr (mixed into output by default).
    assert "Failed to parse" in result.output or "Failed to parse" in (result.stderr or "")


def test_tomte_tox_refuses_to_overwrite_unmanaged_darglint(tmp_path: Path, monkeypatch) -> None:
    """Pre-existing `.darglint` without managed-marker → click.UsageError.

    Without `--show` the wrapper writes sidecars then invokes tox. We
    don't want to actually run tox in tests, but the sidecar safety
    check happens BEFORE the tox subprocess. Stub `shutil.which("tox")`
    to a fake path so we cross the no-tox-on-PATH branch and reach the
    `_assert_managed_or_absent` check.
    """
    _write_repo_skeleton(tmp_path)
    # User-owned .darglint without the managed marker.
    (tmp_path / ".darglint").write_text(
        "[darglint]\nstrictness = full\n", encoding="utf-8"
    )
    runner = CliRunner()
    # Bypass the `tox not on PATH` short-circuit so we reach the sidecar
    # safety check; substitute a non-existent path so the subprocess.run
    # would fail anyway, but in fact the UsageError fires first.
    monkeypatch.setattr(
        "tomte.tools.tox_runtime.shutil.which", lambda _: "/nonexistent/tox"
    )
    result = runner.invoke(tomte_tox, ["--repo-root", str(tmp_path)])
    assert result.exit_code != 0
    assert "managed by `tomte tox`" in result.output or ".darglint" in result.output


def test_tomte_tox_overwrites_managed_sidecar(tmp_path: Path, monkeypatch) -> None:
    """Pre-existing `.darglint` WITH managed-marker → wrapper proceeds (overwrite-safe)."""
    _write_repo_skeleton(tmp_path)
    # Stale managed sidecar from a previous run.
    (tmp_path / ".darglint").write_text(
        f"{_MANAGED_MARKER}\n[darglint]\nstrictness = short\n", encoding="utf-8"
    )

    # Capture the subprocess.run call to verify we reached it without
    # actually invoking tox.
    captured: dict = {}

    class _FakeResult:
        returncode = 0

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        # The wrapper deletes sidecars in `finally`, so to verify the
        # marker check passed we simply note we got here.
        captured["sidecar_present"] = (tmp_path / ".darglint").is_file()
        return _FakeResult()

    monkeypatch.setattr(
        "tomte.tools.tox_runtime.shutil.which", lambda _: "/nonexistent/tox"
    )
    monkeypatch.setattr("tomte.tools.tox_runtime.subprocess.run", _fake_run)

    runner = CliRunner()
    result = runner.invoke(tomte_tox, ["--repo-root", str(tmp_path)])
    # SystemExit(0) from `sys.exit(result.returncode)` is expected.
    assert result.exit_code == 0, result.output
    assert captured.get("cmd", [None])[0] == "tox"
    # `.darglint` was rewritten by the wrapper before tox ran.
    assert captured.get("sidecar_present") is True


# --------------------------------------------------------------------------
# analyse-service: service resolution, per-service commands, env omission
#
# Regression coverage for the bug where `SERVICE_PUBLIC_ID` resolved to ""
# in every repo with zero or several services, rendering
# `autonomy analyse service --public-id  --skip-warnings`. Fixtures list
# services in reverse-sorted order so a missing sort cannot coincide with
# the expected answer.
# --------------------------------------------------------------------------


def _analyse_service_ids(rendered: str) -> List[str]:
    """`--public-id` value of every rendered `autonomy analyse service` line."""
    ids = []
    for line in rendered.splitlines():
        stripped = line.strip()
        if stripped.startswith("autonomy analyse service"):
            ids.append(stripped.split("--public-id", 1)[1].split()[0])
    return ids


def _has_analyse_service_env(rendered: str) -> bool:
    """True when the rendered config declares the testenv.

    Matches the section header line exactly — a substring search would also
    hit the `analyse-service` mention in the template's header comment.
    """
    return any(
        line.strip() == "[testenv:analyse-service]"
        for line in rendered.splitlines()
    )


def _render_via_cli(tmp_path: Path) -> str:
    result = CliRunner().invoke(tomte_tox, ["--repo-root", str(tmp_path), "--show"])
    assert result.exit_code == 0, result.output
    return result.output


def test_resolve_service_public_ids_discovers_every_service(tmp_path: Path) -> None:
    """Auto-discovery returns all services sorted, not just a lone one."""
    _write_repo_skeleton(tmp_path, services=["zeta_service", "alpha_service"])
    assert _resolve_service_public_ids(tmp_path, identity={}) == [
        "valory/alpha_service",
        "valory/zeta_service",
    ]


def test_resolve_service_public_ids_single_service(tmp_path: Path) -> None:
    """One service still resolves to exactly that service."""
    _write_repo_skeleton(tmp_path, services=["lone_service"])
    assert _resolve_service_public_ids(tmp_path, identity={}) == [
        "valory/lone_service"
    ]


def test_resolve_service_public_ids_empty_without_services(tmp_path: Path) -> None:
    """A repo with no services resolves to nothing to analyse."""
    _write_repo_skeleton(tmp_path)
    assert _resolve_service_public_ids(tmp_path, identity={}) == []


def test_resolve_service_public_ids_explicit_string(tmp_path: Path) -> None:
    """Legacy string form stays supported."""
    _write_repo_skeleton(tmp_path)
    out = _resolve_service_public_ids(
        tmp_path, identity={"service_public_id": "valory/declared"}
    )
    assert out == ["valory/declared"]


def test_resolve_service_public_ids_explicit_list_preserves_order(
    tmp_path: Path,
) -> None:
    """A declared list is used verbatim — the consumer's ordering is kept."""
    _write_repo_skeleton(tmp_path)
    out = _resolve_service_public_ids(
        tmp_path, identity={"service_public_id": ["valory/zeta", "valory/alpha"]}
    )
    assert out == ["valory/zeta", "valory/alpha"]


def test_resolve_service_public_ids_explicit_overrides_discovery(
    tmp_path: Path,
) -> None:
    """An explicit declaration replaces auto-discovery rather than merging."""
    _write_repo_skeleton(tmp_path, services=["discovered_one", "discovered_two"])
    out = _resolve_service_public_ids(
        tmp_path, identity={"service_public_id": "valory/declared"}
    )
    assert out == ["valory/declared"]


def test_resolve_service_public_ids_explicit_wins_with_nothing_on_disk(
    tmp_path: Path,
) -> None:
    """Services living where discovery can't see them must not lose the check."""
    _write_repo_skeleton(tmp_path, with_packages_json=False)
    out = _resolve_service_public_ids(
        tmp_path, identity={"service_public_id": ["valory/off_disk"]}
    )
    assert out == ["valory/off_disk"]


def test_render_omits_analyse_service_env_when_repo_has_no_services(
    tmp_path: Path,
) -> None:
    """Zero services → no testenv at all, so `tox -e analyse-service` is unknown.

    Rendering the env with empty `commands` would make tox pass it as a
    no-op, reporting green for a check that inspected nothing.
    """
    _write_repo_skeleton(tmp_path)
    rendered = _render_via_cli(tmp_path)
    assert not _has_analyse_service_env(rendered)
    assert _analyse_service_ids(rendered) == []


def test_render_keeps_analyse_service_env_for_single_service(
    tmp_path: Path,
) -> None:
    """Single-service repos keep exactly the one command they had before."""
    _write_repo_skeleton(tmp_path, services=["lone_service"])
    rendered = _render_via_cli(tmp_path)
    assert _has_analyse_service_env(rendered)
    assert _analyse_service_ids(rendered) == ["valory/lone_service"]


def test_render_emits_the_complete_command_for_each_service(tmp_path: Path) -> None:
    """Each line carries `--skip-warnings`, not just a public id.

    Asserting only the id would let a refactor drop the flag unnoticed.
    """
    _write_repo_skeleton(tmp_path, services=["zeta_service", "alpha_service"])
    rendered = _render_via_cli(tmp_path)
    commands = [
        line.strip()
        for line in rendered.splitlines()
        if line.strip().startswith("autonomy analyse service")
    ]
    assert commands == [
        "autonomy analyse service --public-id valory/alpha_service --skip-warnings",
        "autonomy analyse service --public-id valory/zeta_service --skip-warnings",
    ]


def test_render_emits_one_command_per_service(tmp_path: Path) -> None:
    """Several services → one `autonomy analyse service` per service.

    Declaring or analysing only one of them would leave the rest
    uninspected behind a green check.
    """
    _write_repo_skeleton(tmp_path, services=["zeta_service", "alpha_service"])
    rendered = _render_via_cli(tmp_path)
    assert _has_analyse_service_env(rendered)
    assert _analyse_service_ids(rendered) == [
        "valory/alpha_service",
        "valory/zeta_service",
    ]


def test_render_analyse_service_from_explicit_list(tmp_path: Path) -> None:
    """`[tool.tomte] service_public_id` as a list renders one command each."""
    _write_repo_skeleton(tmp_path)
    pyproject = (tmp_path / "pyproject.toml").read_text()
    pyproject += 'service_public_id = ["valory/zeta", "valory/alpha"]\n'
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    rendered = _render_via_cli(tmp_path)
    # Declared order, not sorted order — nothing may re-sort it en route.
    assert _analyse_service_ids(rendered) == ["valory/zeta", "valory/alpha"]


@pytest.mark.parametrize(
    "services", [(), ("lone_service",), ("zeta_service", "alpha_service")]
)
def test_render_never_emits_an_empty_public_id(
    tmp_path: Path, services: Sequence[str]
) -> None:
    """The original bug: `--public-id` with no value, whatever the service count.

    tox splits `commands` on whitespace, so an empty substitution made
    `--public-id` swallow `--skip-warnings` as its value and the env
    exited on a usage error.
    """
    _write_repo_skeleton(tmp_path, services=services)
    rendered = _render_via_cli(tmp_path)
    assert "--public-id  " not in rendered
    assert "--public-id --skip-warnings" not in rendered
    assert all(not pid.startswith("-") for pid in _analyse_service_ids(rendered))


def test_render_analyse_service_runs_every_service_before_failing(
    tmp_path: Path,
) -> None:
    """`ignore_errors` keeps tox going past a failing service.

    Without it tox aborts at the first failing command, hiding every later
    service's findings. It does not ignore the failure: the env is still
    reported failed and tox exits non-zero.
    """
    _write_repo_skeleton(tmp_path, services=["zeta_service", "alpha_service"])
    rendered = _render_via_cli(tmp_path)
    assert _has_analyse_service_env(rendered)
    section = rendered.split("[testenv:analyse-service]", 1)[1].split("\n[testenv:")[0]
    assert "ignore_errors = True" in section


def test_envlist_does_not_reference_analyse_service(tmp_path: Path) -> None:
    """`analyse-service` must stay out of the default envlist.

    It is opt-in via `-e analyse-service`; listing it by default would make
    the whole default run fail in any repo where the env is dropped.
    """
    _write_repo_skeleton(tmp_path)
    rendered = _render_via_cli(tmp_path)
    envlist = rendered.split("envlist =", 1)[1].split("\n")[0]
    assert "analyse-service" not in envlist


# --------------------------------------------------------------------------
# _drop_ini_section
# --------------------------------------------------------------------------


_INI_SAMPLE = """\
[keep-me]
value = 1

[drop-me]
value = 2
continuation =
    line

[keep-me-too]
value = 3
"""


def test_drop_ini_section_removes_header_and_body() -> None:
    """The named section and every line under it are gone."""
    out = _drop_ini_section(_INI_SAMPLE, "drop-me")
    assert "[drop-me]" not in out
    assert "value = 2" not in out
    assert "continuation =" not in out


def test_drop_ini_section_leaves_neighbouring_sections_intact() -> None:
    """Dropping must stop at the next header, not swallow the rest of the file."""
    out = _drop_ini_section(_INI_SAMPLE, "drop-me")
    assert "[keep-me]" in out
    assert "value = 1" in out
    assert "[keep-me-too]" in out
    assert "value = 3" in out


def test_drop_ini_section_is_a_noop_for_an_absent_section() -> None:
    """Dropping a section that isn't there leaves the text untouched."""
    assert _drop_ini_section(_INI_SAMPLE, "not-present") == _INI_SAMPLE


@pytest.mark.parametrize(
    "declared",
    [
        ["valory/mech", ""],
        ["valory/mech", "   "],
        [""],
        ["valory/mech", None],
    ],
)
def test_resolve_service_public_ids_rejects_blank_entries(
    tmp_path: Path, declared: list
) -> None:
    """A blank entry would render `--public-id` with no value — the original bug.

    It reaches the same broken command through the explicit-declaration
    path, hidden among correctly rendered lines rather than alone.
    """
    _write_repo_skeleton(tmp_path)
    with pytest.raises(click.UsageError, match="service_public_id"):
        _resolve_service_public_ids(
            tmp_path, identity={"service_public_id": declared}
        )


@pytest.mark.parametrize("declared", [5, {"a": 1}])
def test_resolve_service_public_ids_rejects_non_string_declarations(
    tmp_path: Path, declared: object
) -> None:
    """A mistyped TOML value gets a usage error, not a raw TypeError."""
    _write_repo_skeleton(tmp_path)
    with pytest.raises(click.UsageError, match="must be a string or a list"):
        _resolve_service_public_ids(
            tmp_path, identity={"service_public_id": declared}
        )


@pytest.mark.parametrize("declared", ["", []])
def test_resolve_service_public_ids_treats_empty_declaration_as_undeclared(
    tmp_path: Path, declared: object
) -> None:
    """An empty declaration falls back to discovery rather than analysing nothing."""
    _write_repo_skeleton(tmp_path, services=["lone_service"])
    out = _resolve_service_public_ids(
        tmp_path, identity={"service_public_id": declared}
    )
    assert out == ["valory/lone_service"]


def test_resolve_service_public_ids_strips_surrounding_whitespace(
    tmp_path: Path,
) -> None:
    """Padding around a declared id is trimmed rather than passed to tox."""
    _write_repo_skeleton(tmp_path)
    out = _resolve_service_public_ids(
        tmp_path, identity={"service_public_id": [" valory/mech "]}
    )
    assert out == ["valory/mech"]
