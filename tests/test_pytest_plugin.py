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

"""Tests for the tomte pytest plugin (markers + filterwarnings defaults)."""


pytest_plugins = ["pytester"]


_OPT_IN_INI = """
[pytest]
tomte_defaults = true
"""

_NO_OPT_IN_INI = """
[pytest]
tomte_defaults = false
"""


def test_canonical_markers_registered_when_opted_in(pytester):
    """integration and e2e markers resolve under --strict-markers when opted in."""
    pytester.makefile(".ini", tox=_OPT_IN_INI)
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.integration
        def test_marked_integration():
            pass

        @pytest.mark.e2e
        def test_marked_e2e():
            pass
        """
    )
    result = pytester.runpytest_subprocess("--strict-markers", "-q")
    result.assert_outcomes(passed=2)


def test_markers_unregistered_when_not_opted_in(pytester):
    """Plugin is silent when tomte_defaults is unset; --strict-markers rejects."""
    pytester.makefile(".ini", tox=_NO_OPT_IN_INI)
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.integration
        def test_marked_integration():
            pass
        """
    )
    result = pytester.runpytest_subprocess("--strict-markers", "-q")
    # --strict-markers turns unknown markers into errors at collection time
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*'integration' not found in `markers`*"])


def test_aea_deprecation_warning_filtered_when_opted_in(pytester):
    """DeprecationWarning emitted from an aea.* module is suppressed when opted in."""
    pytester.makefile(".ini", tox=_OPT_IN_INI)
    pytester.makepyfile(
        """
        import sys
        import types
        import warnings

        aea_pkg = types.ModuleType("aea")
        aea_foo = types.ModuleType("aea.foo")
        aea_pkg.foo = aea_foo
        sys.modules["aea"] = aea_pkg
        sys.modules["aea.foo"] = aea_foo

        def emit():
            warnings.warn("legacy aea API", DeprecationWarning, stacklevel=2)

        aea_foo.emit = emit

        def test_aea_warning_does_not_error():
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                pass
        """
    )
    result = pytester.runpytest("-W", "error::DeprecationWarning", "-q")
    result.assert_outcomes(passed=1)


def test_truthy_values_accepted(pytester):
    """Common truthy spellings (true/1/yes/on) all opt in."""
    for raw in ("true", "TRUE", "1", "yes", "on"):
        pytester.makefile(".ini", tox=f"[pytest]\ntomte_defaults = {raw}\n")
        pytester.makepyfile(
            """
            import pytest

            @pytest.mark.integration
            def test_marked():
                pass
            """
        )
        result = pytester.runpytest_subprocess("--strict-markers", "-q")
        result.assert_outcomes(passed=1)
