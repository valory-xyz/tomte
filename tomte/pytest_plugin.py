# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""Tomte pytest plugin — ships canonical pytest defaults to consumer repos.

Loaded automatically by pytest via the `pytest11` entry point declared in
tomte's pyproject.toml. Repos extend or override via their own pytest config
(tox.ini [pytest], pyproject [tool.pytest.ini_options], pytest.ini).
"""

import pytest


_DEFAULT_MARKERS = (
    "integration: marks integration tests which require other network services",
    "e2e: marks end-to-end agent tests",
)

_DEFAULT_FILTERWARNINGS = (
    "ignore::DeprecationWarning:aea.*:",
)


def pytest_configure(config: pytest.Config) -> None:
    """Register canonical markers and warning filters."""
    for marker in _DEFAULT_MARKERS:
        config.addinivalue_line("markers", marker)
    for entry in _DEFAULT_FILTERWARNINGS:
        config.addinivalue_line("filterwarnings", entry)
