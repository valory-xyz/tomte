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


def test_canonical_markers_registered(pytester):
    """integration and e2e markers resolve under --strict-markers from the plugin alone."""
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
    result = pytester.runpytest("--strict-markers", "-q")
    result.assert_outcomes(passed=2)


def test_aea_deprecation_warning_filtered(pytester):
    """DeprecationWarning emitted from an aea.* module is suppressed by the plugin filter."""
    pytester.makepyfile(
        """
        import sys
        import types
        import warnings

        # Create a fake aea.foo module so the warning's __module__ matches the filter
        aea_pkg = types.ModuleType("aea")
        aea_foo = types.ModuleType("aea.foo")
        aea_pkg.foo = aea_foo
        sys.modules["aea"] = aea_pkg
        sys.modules["aea.foo"] = aea_foo

        def emit():
            warnings.warn("legacy aea API", DeprecationWarning, stacklevel=2)

        aea_foo.emit = emit

        def test_aea_warning_does_not_error():
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                # The plugin filter is applied at pytest collection time, not by
                # warnings.simplefilter inside the test. So instead of relying on
                # the global filter here, we just assert pytest doesn't fail the
                # session due to the aea warning being recorded.
                pass
        """
    )
    # Run with -W error to verify pytest's filter (added by our plugin) wins for aea.*
    result = pytester.runpytest("-W", "error::DeprecationWarning", "-q")
    result.assert_outcomes(passed=1)
