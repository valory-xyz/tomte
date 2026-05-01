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


_AEA_FILTERWARNINGS_INTROSPECTION = """
def test_aea_filter_present(pytestconfig):
    entries = pytestconfig.getini("filterwarnings")
    assert "ignore::DeprecationWarning:aea.*:" in entries


def test_aea_filter_absent(pytestconfig):
    entries = pytestconfig.getini("filterwarnings")
    assert "ignore::DeprecationWarning:aea.*:" not in entries
"""


def test_aea_deprecation_filter_registered_when_opted_in(pytester):
    """Opt-in registers the aea.* DeprecationWarning ignore in pytest's filterwarnings.

    Behavioural verification (running pytest with `-W error` and asserting
    a warning fires/doesn't fire) is misleading because CLI `-W` is
    evaluated AFTER ini `filterwarnings` — Python's last-match-wins rule
    means a CLI `-W error` always trumps our ini-level ignore. Instead,
    introspect the resolved ini list directly: that's what pytest's
    warning machinery consults at runtime.
    """
    pytester.makefile(".ini", tox=_OPT_IN_INI)
    pytester.makepyfile(_AEA_FILTERWARNINGS_INTROSPECTION)
    result = pytester.runpytest_subprocess("-q", "-k", "test_aea_filter_present")
    result.assert_outcomes(passed=1)


def test_aea_deprecation_filter_silent_when_not_opted_in(pytester):
    """Without opt-in, the aea.* filter is NOT in pytest's filterwarnings list."""
    pytester.makefile(".ini", tox=_NO_OPT_IN_INI)
    pytester.makepyfile(_AEA_FILTERWARNINGS_INTROSPECTION)
    result = pytester.runpytest_subprocess("-q", "-k", "test_aea_filter_absent")
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
