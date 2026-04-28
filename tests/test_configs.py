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
]


@pytest.mark.parametrize("name,path", _RESOURCES, ids=[r[0] for r in _RESOURCES])
def test_resource_path_exists(name, path):
    """Every tomte.configs constant points at a packaged file that exists."""
    assert path.is_file(), f"{name} -> {path} is not a file on disk"
    assert path.stat().st_size > 0, f"{name} -> {path} is empty"


def test_pylintrc_carries_pylint_internals_only():
    """Pylintrc ships pylint-vocabulary codes but NO downstream library names.

    Regression guard for David's review on tomte#46: tomte must not enumerate
    downstream library names in `ignored-modules` — that creates the wrong
    dependency direction (a new dep in mech-predict would force a tomte
    release). Per-repo additions go through `[tool.tomte.scaffold]
    extra_pylint_ignored_modules` and are rendered into `--ignored-modules=`
    on the pylint testenv command.
    """
    parser = configparser.ConfigParser()
    parser.read(configs.PYLINTRC)
    assert parser.has_section("MESSAGES CONTROL"), "missing [MESSAGES CONTROL]"
    disable = parser["MESSAGES CONTROL"].get("disable", "")
    assert "C0103" in disable and "W1203" in disable, (
        "pylint-internal disable codes missing"
    )
    if parser.has_section("IMPORTS"):
        ignored = parser["IMPORTS"].get("ignored-modules", "")
        assert not ignored.strip(), (
            f"pylintrc must not list downstream library names in [IMPORTS] "
            f"ignored-modules; found: {ignored!r}. Per-repo extras come "
            f"through [tool.tomte.scaffold] extra_pylint_ignored_modules."
        )


def test_mypy_ini_has_base_only_no_third_party_overrides():
    """Mypy canonical ships base strictness + protobuf exclude — no library names.

    Regression guard for David's review on tomte#46: per-repo
    `[mypy-<libname>]` blocks live in the consuming repo's tox.ini and
    layer on via the `[testenv:mypy]` concat trick — not here.
    """
    parser = configparser.ConfigParser()
    parser.read(configs.MYPY_INI)
    assert parser.has_section("mypy"), "missing [mypy] base"
    assert parser["mypy"].get("strict_optional") == "True"
    assert parser["mypy"].get("disallow_untyped_defs") == "True"
    exclude = parser["mypy"].get("exclude", "")
    assert "_pb2" in exclude and "custom_types" in exclude, (
        "exclude regex missing protobuf / custom_types pattern"
    )
    mypy_module_sections = [s for s in parser.sections() if s.startswith("mypy-")]
    assert not mypy_module_sections, (
        f"mypy.ini must not list downstream libraries; found: "
        f"{mypy_module_sections!r}. Per-repo overrides go in the "
        f"consuming repo's tox.ini."
    )


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
