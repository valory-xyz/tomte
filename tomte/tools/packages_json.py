"""Discovery helpers around `packages/packages.json`.

`packages.json` in any open-autonomy / open-aea repo is the canonical
manifest. Its top-level shape is::

    {
        "dev":         { "<type>/<author>/<name>/<version>": "<ipfs_hash>", ... },
        "third_party": { "<type>/<author>/<name>/<version>": "<ipfs_hash>", ... }
    }

`dev` packages are first-party source for the consuming repo; `third_party`
packages are synced from IPFS via `autonomy packages sync`. We use this
split as the source of truth for which packages should be linted, tested,
and copyright-checked — instead of asking each repo to maintain a
hand-curated list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click

# Singular types in packages.json keys → plural directory names on disk.
_TYPE_TO_DIR: Dict[str, str] = {
    "skill": "skills",
    "connection": "connections",
    "contract": "contracts",
    "custom": "customs",
    "agent": "agents",
    "service": "services",
    "protocol": "protocols",
}

# Types that contain Python source code worth running linters against.
# Skips: protocol (auto-generated _pb2.py), agent / service (yaml-only).
_LINTABLE_TYPES: Tuple[str, ...] = ("skill", "connection", "contract", "custom")


def _packages_json_path(repo_root: Path) -> Path:
    return repo_root / "packages" / "packages.json"


def _parse_key(key: str) -> Optional[Tuple[str, str, str]]:
    """Split `<type>/<author>/<name>/<version>` → (type, author, name).

    Returns None for malformed keys so callers can ignore them silently.
    """
    parts = key.split("/")
    if len(parts) != 4:
        return None
    return parts[0], parts[1], parts[2]


def _key_to_path(key: str) -> Optional[Path]:
    parsed = _parse_key(key)
    if parsed is None:
        return None
    pkg_type, author, name = parsed
    type_dir = _TYPE_TO_DIR.get(pkg_type)
    if type_dir is None:
        return None
    return Path("packages", author, type_dir, name)


def load_packages_json(repo_root: Path) -> Optional[Dict[str, Dict[str, str]]]:
    """Return parsed packages.json, or None if the file is absent.

    Raises ``click.UsageError`` on truncated / malformed JSON, or when the
    file is present but lacks both ``dev`` and ``third_party`` top-level
    keys (a typo like ``"devs"`` would otherwise produce empty pytest /
    linter target lists with no breadcrumb to the typo).
    """
    path = _packages_json_path(repo_root)
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise click.UsageError(f"Failed to parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise click.UsageError(
            f"{path}: expected a JSON object at top level, got {type(data).__name__}"
        )
    # Empty `{}` is legitimate bootstrap state for a brand-new fleet repo.
    # Only the typo-guard (e.g. `"devs"` instead of `"dev"`) needs to fire,
    # and that only makes sense when at least one key is present.
    if data and "dev" not in data and "third_party" not in data:
        raise click.UsageError(
            f"{path}: neither 'dev' nor 'third_party' top-level key present "
            f"(found: {sorted(data)}). Check for typos like 'devs'."
        )
    return data


def dev_package_paths(
    repo_root: Path,
    types: Tuple[str, ...] = _LINTABLE_TYPES,
) -> List[str]:
    """Filesystem paths of dev packages, filtered to the given types.

    Used as the default for `service_specific_packages` (linters) and
    `pytest_targets` (tests). Returns empty list when packages.json is
    missing — the wrapper falls back to whatever the consumer declared.
    """
    data = load_packages_json(repo_root)
    if data is None:
        return []
    paths: List[str] = []
    for key in data.get("dev", {}):
        parsed = _parse_key(key)
        if parsed is None:
            continue
        pkg_type, _, _ = parsed
        if pkg_type not in types:
            continue
        path = _key_to_path(key)
        if path is None:
            continue
        paths.append(str(path))
    return paths


def dev_package_test_paths(
    repo_root: Path,
    types: Tuple[str, ...] = _LINTABLE_TYPES,
) -> List[str]:
    """Pytest target paths for every dev package that has tests.

    Two layouts are recognised:

    - ``<pkg>/tests/`` — the canonical autonomy layout (skills, connections,
      contracts). Returned as the directory path.
    - ``<pkg>/test_*.py`` at the package root — used by ``customs/`` because
      autonomy ships them as single-file Python modules, not packages with
      a tests subdir. Returned as one path per matched file.
    """
    out: List[str] = []
    for path_str in dev_package_paths(repo_root, types=types):
        pkg_dir = repo_root / path_str
        tests_dir = pkg_dir / "tests"
        if tests_dir.is_dir():
            out.append(str(Path(path_str) / "tests"))
            continue
        for test_file in sorted(pkg_dir.glob("test_*.py")):
            out.append(str(Path(path_str) / test_file.name))
    return out


def third_party_package_names(repo_root: Path) -> List[str]:
    """Names (last `<name>` segment) of third-party packages.

    Used by copyright-check to exclude packages we don't own. Names are
    de-duplicated and sorted for deterministic output.
    """
    data = load_packages_json(repo_root)
    if data is None:
        return []
    names = set()
    for key in data.get("third_party", {}):
        parsed = _parse_key(key)
        if parsed is None:
            continue
        _, _, name = parsed
        names.add(name)
    return sorted(names)


def discover_service_public_id(repo_root: Path) -> Optional[str]:
    """Single-service repos: return `<author>/<name>` from `packages.json`.

    Used for `autonomy analyse service`. If the repo has zero or multiple
    services, returns None — the caller should require the consumer to
    declare it explicitly.
    """
    data = load_packages_json(repo_root)
    if data is None:
        return None
    services = []
    for key in data.get("dev", {}):
        parsed = _parse_key(key)
        if parsed is None:
            continue
        pkg_type, author, name = parsed
        if pkg_type == "service":
            services.append(f"{author}/{name}")
    if len(services) == 1:
        return services[0]
    return None
