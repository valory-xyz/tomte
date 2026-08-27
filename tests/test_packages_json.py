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

"""Direct tests for `tomte.tools.packages_json.load_packages_json` error handling.

Each raise site has a regression test so a future refactor can't quietly
drop a guard (e.g. flipping `and` to `or` in the missing-keys check, or
removing the `isinstance` check after a typing pass).
"""

import json
import re
from pathlib import Path

import click
import pytest

from tomte.tools.packages_json import (
    discover_service_public_ids,
    load_packages_json,
)


def _write_packages_json(repo_root: Path, content: str) -> Path:
    pkg_dir = repo_root / "packages"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    target = pkg_dir / "packages.json"
    target.write_text(content, encoding="utf-8")
    return target


def test_returns_none_when_file_absent(tmp_path: Path) -> None:
    """No file at the expected path → None (not an error)."""
    assert load_packages_json(tmp_path) is None


def test_dev_only_happy_path(tmp_path: Path) -> None:
    """Single-key `{"dev": {...}}` is valid; regression guard against `and → or` flip."""
    _write_packages_json(tmp_path, json.dumps({"dev": {"skill/valory/foo/0.1.0": "bafy..."}}))
    data = load_packages_json(tmp_path)
    assert data == {"dev": {"skill/valory/foo/0.1.0": "bafy..."}}


def test_third_party_only_happy_path(tmp_path: Path) -> None:
    """Single-key `{"third_party": {...}}` is also valid (e.g. for a consumer-pure repo)."""
    _write_packages_json(tmp_path, json.dumps({"third_party": {"protocol/x/y/1.0.0": "bafy"}}))
    data = load_packages_json(tmp_path)
    assert data == {"third_party": {"protocol/x/y/1.0.0": "bafy"}}


def test_empty_object_is_legitimate_bootstrap(tmp_path: Path) -> None:
    """`{}` is the legitimate brand-new-fleet-repo state and must not error."""
    _write_packages_json(tmp_path, "{}")
    data = load_packages_json(tmp_path)
    assert data == {}


def test_truncated_json_raises_with_path_in_message(tmp_path: Path) -> None:
    """JSONDecodeError surfaces as click.UsageError with the offending path."""
    target = _write_packages_json(tmp_path, '{"dev": {')  # truncated
    with pytest.raises(click.UsageError) as excinfo:
        load_packages_json(tmp_path)
    assert str(target) in str(excinfo.value)


def test_top_level_list_rejected_with_type_name(tmp_path: Path) -> None:
    """A top-level array is not a JSON object — error names the unexpected type."""
    _write_packages_json(tmp_path, json.dumps(["not", "an", "object"]))
    with pytest.raises(click.UsageError, match=r"got list"):
        load_packages_json(tmp_path)


def test_top_level_string_rejected_with_type_name(tmp_path: Path) -> None:
    """A top-level scalar likewise rejected."""
    _write_packages_json(tmp_path, json.dumps("plain string"))
    with pytest.raises(click.UsageError, match=r"got str"):
        load_packages_json(tmp_path)


def test_devs_typo_caught_with_discovered_keys(tmp_path: Path) -> None:
    """`{"devs": {...}}` (instead of `"dev"`) raises and message includes the actual keys."""
    _write_packages_json(tmp_path, json.dumps({"devs": {"skill/x/y/0.1.0": "bafy"}}))
    with pytest.raises(click.UsageError) as excinfo:
        load_packages_json(tmp_path)
    msg = str(excinfo.value)
    assert "devs" in msg
    assert re.search(r"\['devs'\]", msg) or "found:" in msg


def test_unrelated_keys_only_caught(tmp_path: Path) -> None:
    """Any non-empty object lacking both `dev` and `third_party` raises."""
    _write_packages_json(tmp_path, json.dumps({"unrelated": {}}))
    with pytest.raises(click.UsageError, match=r"neither 'dev' nor 'third_party'"):
        load_packages_json(tmp_path)


# --------------------------------------------------------------------------
# discover_service_public_ids
#
# Fixtures use author `acme` (not `valory`) so a hardcoded author would
# fail, and list services in reverse-sorted insertion order so a missing
# sort cannot coincide with the expected answer.
# --------------------------------------------------------------------------


def test_discover_service_public_ids_returns_empty_without_packages_json(
    tmp_path: Path,
) -> None:
    """No packages.json → no services (not an error)."""
    assert discover_service_public_ids(tmp_path) == []


def test_discover_service_public_ids_returns_empty_when_repo_has_no_services(
    tmp_path: Path,
) -> None:
    """A repo of skills/contracts only yields nothing to analyse."""
    _write_packages_json(
        tmp_path,
        json.dumps(
            {
                "dev": {
                    "skill/acme/alpha/0.1.0": "bafy",
                    "contract/acme/beta/0.1.0": "bafy",
                },
                "third_party": {"service/other/vendor_service/0.1.0": "bafy"},
            }
        ),
    )
    assert discover_service_public_ids(tmp_path) == []


def test_discover_service_public_ids_single_service(tmp_path: Path) -> None:
    """A lone service is returned as a one-element list."""
    _write_packages_json(
        tmp_path,
        json.dumps(
            {
                "dev": {
                    "skill/acme/alpha/0.1.0": "bafy",
                    "service/acme/lone_service/0.1.0": "bafy",
                }
            }
        ),
    )
    assert discover_service_public_ids(tmp_path) == ["acme/lone_service"]


def test_discover_service_public_ids_multiple_sorted_and_type_filtered(
    tmp_path: Path,
) -> None:
    """Every dev service is returned, sorted, with non-service types excluded.

    `zeta_service` is inserted before `alpha_service` so insertion order
    differs from sorted order. The skill and contract entries are named to
    look like services so a broken type filter produces extra entries
    rather than an identical list.
    """
    _write_packages_json(
        tmp_path,
        json.dumps(
            {
                "dev": {
                    "service/acme/zeta_service/0.1.0": "bafy",
                    "skill/acme/decoy_service/0.1.0": "bafy",
                    "service/acme/alpha_service/0.1.0": "bafy",
                    "contract/acme/another_service/0.1.0": "bafy",
                },
                "third_party": {"service/vendor/third_party_service/0.1.0": "bafy"},
            }
        ),
    )
    assert discover_service_public_ids(tmp_path) == [
        "acme/alpha_service",
        "acme/zeta_service",
    ]


def test_discover_service_public_ids_ignores_malformed_keys(tmp_path: Path) -> None:
    """Keys that aren't `<type>/<author>/<name>/<version>` are skipped silently."""
    _write_packages_json(
        tmp_path,
        json.dumps(
            {
                "dev": {
                    "service/acme/good_service/0.1.0": "bafy",
                    "service/acme/missing_version": "bafy",
                    "garbage": "bafy",
                }
            }
        ),
    )
    assert discover_service_public_ids(tmp_path) == ["acme/good_service"]


def test_discover_service_public_ids_deduplicates_across_versions(
    tmp_path: Path,
) -> None:
    """Two versions of one service mid-bump are still one thing to analyse."""
    _write_packages_json(
        tmp_path,
        json.dumps(
            {
                "dev": {
                    "service/acme/zeta_service/0.2.0": "bafy",
                    "service/acme/mech/0.1.0": "bafy",
                    "service/acme/mech/0.2.0": "bafy",
                }
            }
        ),
    )
    assert discover_service_public_ids(tmp_path) == [
        "acme/mech",
        "acme/zeta_service",
    ]
