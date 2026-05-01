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

"""Release gate for tomte.configs: every helper must return an existing file."""

import configparser

import pytest

from tomte import configs


_RESOURCES = [
    ("PYLINTRC", configs.PYLINTRC),
    ("MYPY_INI", configs.MYPY_INI),
    ("ISORT_CFG", configs.ISORT_CFG),
    ("FLAKE8_CFG", configs.FLAKE8_CFG),
    ("DARGLINT_CFG", configs.DARGLINT_CFG),
    ("BANDIT_YAML", configs.BANDIT_YAML),
    ("SAFETY_POLICY", configs.SAFETY_POLICY),
    ("GITLEAKS_TOML", configs.GITLEAKS_TOML),
]


@pytest.mark.parametrize("name,path", _RESOURCES, ids=[r[0] for r in _RESOURCES])
def test_resource_path_exists(name, path):
    """Every tomte.configs constant points at a packaged file that exists."""
    assert path.is_file(), f"{name} -> {path} is not a file on disk"
    assert path.stat().st_size > 0, f"{name} -> {path} is empty"


def test_pylintrc_carries_pylint_internals_only():
    """Pylintrc ships pylint-vocabulary codes but no downstream library names."""
    parser = configparser.ConfigParser()
    parser.read(configs.PYLINTRC)
    assert parser.has_section("MESSAGES CONTROL")
    disable = parser["MESSAGES CONTROL"].get("disable", "")
    assert "C0103" in disable and "W1203" in disable
    if parser.has_section("IMPORTS"):
        ignored = parser["IMPORTS"].get("ignored-modules", "")
        assert not ignored.strip(), f"unexpected ignored-modules: {ignored!r}"


def test_mypy_ini_carries_framework_third_party_blocks():
    """Mypy canonical ships base strictness, protobuf exclude, and framework-level
    `[mypy-<lib>]` blocks for libraries that recur across the fleet.

    Repo-specific `[mypy-<lib>]` overrides still live in each consumer's tox.ini
    and layer on at runtime via `tomte render-mypy-config --append-from`.
    """
    parser = configparser.ConfigParser()
    parser.read(configs.MYPY_INI)
    assert parser.has_section("mypy")
    assert parser["mypy"].get("strict_optional") == "True"
    assert parser["mypy"].get("disallow_untyped_defs") == "True"
    exclude = parser["mypy"].get("exclude", "")
    assert "_pb2" in exclude and "custom_types" in exclude
    # Framework libs without type stubs that should be centralised so
    # every fleet repo doesn't re-declare them. Sentinel set, not exhaustive.
    blocks = {s for s in parser.sections() if s.startswith("mypy-")}
    expected = {
        "mypy-aea.*",
        "mypy-autonomy.*",
        "mypy-web3.*",
        "mypy-packages.open_aea.*",
    }
    missing = expected - blocks
    assert not missing, f"expected framework blocks missing from canonical: {missing!r}"
    # Every centralised block should declare exactly one allowed knob:
    # ignore_missing_imports (libs without type stubs) or ignore_errors
    # (vendored package trees synced from IPFS, e.g. packages.open_aea.*,
    # packages.fetchai.*). Anything else implies the canonical is taking a
    # stronger stance than the consumer-extensible policy supports.
    _ALLOWED_KNOBS = {"ignore_missing_imports", "ignore_errors"}
    for section in blocks:
        keys = set(parser[section].keys())
        assert keys.issubset(_ALLOWED_KNOBS), (
            f"[{section}] declares unsupported keys: {keys - _ALLOWED_KNOBS!r}"
        )
        for key in keys:
            assert parser[section][key] == "True", (
                f"[{section}] {key} must be True (got {parser[section][key]!r})"
            )


def test_isort_canonical_carries_no_per_repo_packaging_facts():
    """Isort canonical must not encode per-repo packaging identity."""
    parser = configparser.ConfigParser()
    parser.read(configs.ISORT_CFG)
    assert parser.has_section("isort")
    settings = parser["isort"]
    for key in ("known_first_party", "known_packages", "known_local_folder"):
        assert key not in settings, f"unexpected key: {key}"


def test_safety_policy_is_yaml_shaped():
    """Canonical safety policy must parse as YAML and have the expected keys."""
    text = configs.SAFETY_POLICY.read_text(encoding="utf-8")
    assert "ignore-vulnerabilities" in text
    assert "continue-on-vulnerability-error" in text


def test_bandit_yaml_skips_assert_used():
    """Canonical bandit policy must skip B101 (assertions inside test paths)."""
    text = configs.BANDIT_YAML.read_text(encoding="utf-8")
    assert "B101" in text
    assert "exclude_dirs" in text


def test_gitleaks_canonical_carries_rules_and_allowlist():
    """Canonical gitleaks config must ship the rule set + fleet allowlist."""
    text = configs.GITLEAKS_TOML.read_text(encoding="utf-8")
    rules = text.count("\n[[rules]]")
    assert rules >= 90, f"gitleaks rule count regressed: {rules}"
    assert "0x[0-9a-fA-F]{40}" in text
    assert "bafybei" in text
    assert "'''ui-build" not in text
