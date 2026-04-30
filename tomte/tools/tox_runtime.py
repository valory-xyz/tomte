"""`tomte tox` — runtime wrapper that runs tox against tomte's canonical config.

Replaces the older `tomte scaffold tox` flow that copied a 500+ line tox.ini
into every consuming repo. Instead, the canonical tox.ini lives only in
tomte; consuming repos carry only their identity (an optional `[tool.tomte]`
section in pyproject.toml) and, in rare cases, a small `[tomte-extensions]`
section in a local `tox.ini` for things that don't fit cleanly in TOML
(extra deps with version pins, pylint extras, mypy per-package overrides).

The wrapper reads pyproject + (optional) local extensions, renders tomte's
canonical tox.ini into a temp file in the repo root, writes companion
config files (`.darglint`, `.gitleaks-merged.toml`) the canonical envs
reference, and invokes `tox -c <temp-file> <args>`.
"""

from __future__ import annotations

import configparser
import re
import subprocess
import sys
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

try:
    import tomllib
except ImportError:  # py3.10
    import tomli as tomllib  # type: ignore[no-redef]

import click

from tomte import __version__
from tomte.configs import GITLEAKS_TOML, TOX_INI
from tomte.tools.packages_json import (
    dev_package_paths,
    dev_package_test_paths,
    discover_service_public_id,
    load_packages_json,
    third_party_package_names,
)


# Hardcoded fleet-wide constants. Previously per-repo `[tool.tomte]` keys;
# moved here because they never vary across consumers downstream of OA.
_KNOWN_FIRST_PARTY = "autonomy"

# Multi-line continuation values need re-indenting after configparser strip.
_DEPS_INDENT = 4

# Filename for the rendered tox.ini in the consuming repo. Hidden so a
# stray `ls` doesn't surprise people; deterministic so the wrapper can
# overwrite cleanly across runs.
_RENDERED_TOX_FILENAME = ".tomte-tox.ini"

# darglint has no `--config-file` flag and reads from `[darglint]` in
# tox.ini / setup.cfg / .darglint in CWD. Since the rendered tox.ini lives
# at `.tomte-tox.ini` (not a name darglint searches), we drop a `.darglint`
# alongside it at runtime so all consumers share fleet-uniform settings
# without having to copy the block into their own tox.ini.
_RENDERED_DARGLINT_FILENAME = ".darglint"
_DARGLINT_CONFIG = """[darglint]
docstring_style = sphinx
strictness = short
ignore_regex = async_act|.*_pb2\\.py
ignore = DAR401
"""

# Gitleaks has no built-in mechanism to merge a base config with per-repo
# allowlist additions; the standard pattern is `[extend].path` pointing at
# the base config + a local `[allowlist].paths` section. The wrapper writes
# this merged file at runtime so the canonical [testenv:gitleaks] env can
# reference a deterministic path.
_RENDERED_GITLEAKS_FILENAME = ".gitleaks-merged.toml"

# PEP 508 dep matcher — extracts the leftmost package name token. Used to
# classify deps for the auto-derived [tomte-extensions] extra_deps.
_DEP_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.\-]*)")
# PEP 508 strict-pin matcher (name==version) for version discovery.
_PIN_RE = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9_\-]*)\s*(?:\[[A-Za-z0-9_\-,\s]+\])?\s*==\s*([0-9A-Za-z\.\-_]+)"
)

# Dep names that the canonical [deps-packages] block already pins; auto-
# derived extra_deps must skip these to avoid duplicate-version conflicts.
_CANONICAL_DEP_NAMES: Set[str] = {
    "open-autonomy",
    "open-aea",
    "open-aea-ledger-ethereum",
    "open-aea-ledger-cosmos",
    "open-aea-test-autonomy",
    "open-aea-cli-ipfs",
    "open-aea-helpers",
    # Lint-time deps shipped by tomte's own [deps-tests]/[testenv:*] envs.
    "tomte",
    "pip",
    "setuptools",
}


def _read_pyproject(repo_root: Path) -> Dict[str, Any]:
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.is_file():
        raise click.UsageError(f"No pyproject.toml at {pyproject_path}")
    with pyproject_path.open("rb") as fh:
        return tomllib.load(fh)


def _read_tomte_section(pyproject: Dict[str, Any]) -> Dict[str, Any]:
    return pyproject.get("tool", {}).get("tomte", {}) or {}


def _parse_versions_from_dependencies(
    pyproject: Dict[str, Any],
) -> Tuple[Optional[str], Optional[str]]:
    """Pull (open_autonomy_version, open_aea_version) out of [project].dependencies.

    These versions appear as exact pins on `open-autonomy` and one of the
    `open-aea-ledger-*` packages — both required across the agent fleet.
    Returning None for either means the consumer omitted the canonical
    pin and must declare the version explicitly in [tool.tomte].
    """
    deps = pyproject.get("project", {}).get("dependencies", []) or []
    autonomy_version: Optional[str] = None
    aea_version: Optional[str] = None
    for dep in deps:
        match = _PIN_RE.match(dep)
        if not match:
            continue
        name, version = match.group(1).lower(), match.group(2)
        if name == "open-autonomy":
            autonomy_version = version
        elif aea_version is None and name.startswith("open-aea-ledger-"):
            aea_version = version
    return autonomy_version, aea_version


def _read_local_extensions(repo_root: Path, local_path: Optional[str]) -> Dict[str, str]:
    """Read `[tomte-extensions]` and any raw `[testenv:*]` sections from the local tox.ini.

    `[tomte-extensions]` is parsed via configparser (typed keys → string
    values). `[testenv:*]` sections are extracted as raw text so that
    multi-line tox `commands` blocks keep their indentation — configparser
    strips leading whitespace from continuation lines, which would break
    line-continuation syntax in pytest invocations etc.
    """
    if not local_path:
        return {}
    full_path = repo_root / local_path
    if not full_path.is_file():
        return {}
    parser = configparser.ConfigParser(strict=False)
    parser.read(full_path, encoding="utf-8")
    out: Dict[str, str] = {}
    if parser.has_section("tomte-extensions"):
        out.update(parser.items("tomte-extensions"))
    out["_raw_passthrough"] = _extract_raw_passthrough_sections(full_path)
    return out


# Sections the wrapper handles itself; everything else in the local tox.ini
# is copied verbatim into the rendered output. `[darglint]` is dropped
# silently because tomte renders its own .darglint at runtime.
_MANAGED_SECTIONS = {"tomte-extensions", "darglint"}


def _is_managed(section_name: str) -> bool:
    return section_name in _MANAGED_SECTIONS or section_name.startswith("mypy")


def _extract_raw_passthrough_sections(path: Path) -> str:
    """Return every section the wrapper does NOT manage, verbatim.

    `[tomte-extensions]`, `[mypy*]`, and `[darglint]` are parsed/read
    elsewhere; everything else (e.g. `[testenv:coverage]`, `[Authorized
    Packages]`, `[pytest]`) is concatenated verbatim into the rendered
    tox.ini so multi-line `commands` continuations and other indentation
    survive intact.
    """
    blocks: List[List[str]] = []
    current: Optional[List[str]] = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        is_section_header = stripped.startswith("[") and stripped.endswith("]")
        if is_section_header:
            section_name = stripped[1:-1]
            if _is_managed(section_name):
                current = None
            else:
                current = [line]
                blocks.append(current)
            continue
        if current is not None:
            current.append(line)
    if not blocks:
        return ""
    return "\n".join("\n".join(block).rstrip() for block in blocks)


def _reindent(value: str, indent: int) -> str:
    stripped = value.strip("\n")
    if not stripped:
        return ""
    prefix = " " * indent
    return "\n".join(
        (prefix + line) if line.strip() else line
        for line in stripped.splitlines()
    )


def _render_pylint_flags(extensions: Dict[str, str], identity: Dict[str, Any]) -> str:
    flags: List[str] = []
    raw_modules = extensions.get("extra_pylint_ignored_modules", "").strip()
    if raw_modules:
        flags.append(f"--ignored-modules={raw_modules}")
    raw_disables = extensions.get("extra_pylint_disables", "").strip()
    # Allow [tool.tomte] pylint_disables list as a cleaner alternative.
    list_disables = identity.get("pylint_disables")
    if list_disables and not raw_disables:
        if isinstance(list_disables, list):
            raw_disables = ",".join(list_disables)
        else:
            raw_disables = str(list_disables)
    if raw_disables:
        flags.append(f"--disable={raw_disables}")
    return " ".join(flags)


def _join_listish(value: Union[str, Sequence[str]]) -> str:
    if isinstance(value, str):
        return value
    return " ".join(value)


def _subtract(paths: Sequence[str], excluded: Sequence[str]) -> List[str]:
    excluded_set = {p.rstrip("/") for p in excluded}
    return [p for p in paths if p.rstrip("/") not in excluded_set]


def _resolve_pytest_targets(
    repo_root: Path, identity: Dict[str, Any]
) -> List[str]:
    explicit = identity.get("pytest_targets")
    if explicit:
        return list(explicit) if not isinstance(explicit, str) else [explicit]
    discovered = dev_package_test_paths(repo_root)
    return _subtract(discovered, identity.get("pytest_targets_exclude", []) or [])


def _resolve_service_specific_packages(
    repo_root: Path, identity: Dict[str, Any]
) -> List[str]:
    explicit = identity.get("service_specific_packages")
    if explicit:
        return list(explicit) if not isinstance(explicit, str) else [explicit]
    discovered = dev_package_paths(repo_root)
    return _subtract(
        discovered, identity.get("service_specific_packages_exclude", []) or []
    )


def _resolve_versions(
    pyproject: Dict[str, Any], identity: Dict[str, Any]
) -> Tuple[str, str]:
    autonomy = identity.get("open_autonomy_version")
    aea = identity.get("open_aea_version")
    if autonomy and aea:
        return autonomy, aea
    parsed_autonomy, parsed_aea = _parse_versions_from_dependencies(pyproject)
    autonomy = autonomy or parsed_autonomy
    aea = aea or parsed_aea
    if not autonomy:
        raise click.UsageError(
            "Could not determine open-autonomy version. Either pin "
            "`open-autonomy==X.Y.Z` in [project].dependencies or set "
            "`open_autonomy_version` in [tool.tomte]."
        )
    if not aea:
        raise click.UsageError(
            "Could not determine open-aea version. Either pin an "
            "`open-aea-ledger-*==X.Y.Z` in [project].dependencies or set "
            "`open_aea_version` in [tool.tomte]."
        )
    return autonomy, aea


def _detect_packages_paths(repo_root: Path, identity: Dict[str, Any]) -> str:
    """Auto-detect `packages_paths` when the consumer omits it.

    Convention: `packages/<author>/{skills,contracts,connections,...}/`.
    Strategy (most specific first):

    1. Prefer the author of `dev` packages in `packages.json`. The dir for
       third-party packages (typically `packages/open_aea/`, `packages/fetchai/`)
       is also present on disk but does NOT own dev code; using the
       packages.json `dev` author resolves that ambiguity.
    2. Fall back to scanning `packages/<author>/` for known type subdirs;
       use the unique candidate if there's exactly one.

    Raises if neither path yields a single answer.
    """
    explicit = identity.get("packages_paths")
    if explicit:
        return explicit

    data = load_packages_json(repo_root)
    if data is not None:
        dev_authors: Set[str] = set()
        for key in data.get("dev", {}):
            parts = key.split("/")
            if len(parts) == 4:
                dev_authors.add(parts[1])
        if len(dev_authors) == 1:
            return f"packages/{next(iter(dev_authors))}"

    packages_dir = repo_root / "packages"
    if not packages_dir.is_dir():
        raise click.UsageError(
            "Could not auto-detect `packages_paths`: packages/ does not exist. "
            "Set `packages_paths` in [tool.tomte] or create the directory."
        )
    known_subtypes = {
        "skills", "contracts", "connections", "customs",
        "agents", "services", "protocols",
    }
    candidates: List[Path] = []
    for child in sorted(packages_dir.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        if any((child / sub).is_dir() for sub in known_subtypes):
            candidates.append(child)
    if len(candidates) == 1:
        return f"packages/{candidates[0].name}"
    if not candidates:
        raise click.UsageError(
            "Could not auto-detect `packages_paths`: packages/ has no author "
            "directory containing skills/contracts/connections/customs. "
            "Set `packages_paths` in [tool.tomte]."
        )
    raise click.UsageError(
        "Could not auto-detect `packages_paths`: packages/ has multiple "
        f"author directories ({', '.join(c.name for c in candidates)}) "
        "and packages.json does not disambiguate. Set `packages_paths` "
        "in [tool.tomte] explicitly."
    )


def _detect_local_extensions(repo_root: Path, identity: Dict[str, Any]) -> Optional[str]:
    explicit = identity.get("local_extensions")
    if explicit:
        return explicit
    if (repo_root / "tox.ini").is_file():
        return "tox.ini"
    return None


def _resolve_tomte_dep_pin(identity: Dict[str, Any]) -> str:
    """Return the PEP 508 spec string after `tomte[<extras>]`.

    Defaults to `==<self_version>` so canonical envs install the same tomte
    that's running. Consumers override with `tomte_dep_pin` (e.g. for
    pre-release SHAs) when needed.
    """
    explicit = identity.get("tomte_dep_pin")
    if explicit:
        return explicit
    return f"=={__version__}"


def _autoderive_extra_deps(pyproject: Dict[str, Any]) -> List[str]:
    """Mirror [project].dependencies into [tomte-extensions] extra_deps.

    Tomte's lint/test envs install a flat list of pinned packages; previously
    consumers maintained a parallel list of pins in `[tomte-extensions]
    extra_deps` that drifted from pyproject. Auto-deriving from
    `[project].dependencies` makes pyproject the single source of truth.

    Skips:
      - OA / open-aea / open-aea-ledger-* (already in canonical [deps-packages])
      - tomte / pip / setuptools (canonical envs install these themselves)
      - `[tool.uv.sources]`-resolved deps (no version, just a name)
    """
    deps_raw = pyproject.get("project", {}).get("dependencies", []) or []
    out: List[str] = []
    for dep in deps_raw:
        if not isinstance(dep, str):
            continue
        # Strip inline TOML comments before classification.
        clean = dep.split("#", 1)[0].strip()
        if not clean:
            continue
        match = _DEP_NAME_RE.match(clean)
        if not match:
            continue
        name = match.group(1).lower()
        if name in _CANONICAL_DEP_NAMES or name.startswith("open-aea-ledger-"):
            continue
        # uv source-pinned deps appear in [project].dependencies as a bare
        # name (no `==` etc.). They resolve against [tool.uv.sources]; the
        # tox testenvs can't follow that, so skip.
        if "==" not in clean and ">=" not in clean and "<" not in clean and "~=" not in clean:
            continue
        out.append(clean)
    return out


def _resolve_extra_deps(
    pyproject: Dict[str, Any], extensions: Dict[str, str]
) -> str:
    """Combined extra_deps: auto-derived pyproject pins + lint-only locals.

    Pyproject is the single source of truth for any package that ships at
    runtime: its strict pins win over any local `[tomte-extensions]
    extra_deps` entry for the same name. The local block is reserved for
    lint-time-only deps (e.g. type stubs, formatters' transitive deps)
    that aren't part of the runtime dependency set.
    """
    auto = _autoderive_extra_deps(pyproject)
    local_raw = (extensions.get("extra_deps") or "").strip()
    local: List[str] = []
    if local_raw:
        for line in local_raw.splitlines():
            stripped = line.split(";", 1)[0].strip()
            if stripped:
                local.append(stripped)
    auto_names: Set[str] = set()
    for entry in auto:
        match = _DEP_NAME_RE.match(entry)
        if match:
            auto_names.add(match.group(1).lower())
    deduped_local = [
        d for d in local
        if (m := _DEP_NAME_RE.match(d)) and m.group(1).lower() not in auto_names
    ]
    return "\n".join(auto + deduped_local)


def _resolve_check_handlers_ignores(
    repo_root: Path, identity: Dict[str, Any]
) -> str:
    """`-i <name>` flags for `autonomy analyse handlers`.

    Always includes every third-party package name from packages.json
    (we don't own those handlers, can't lint them). Merge semantics for
    consumer overrides:

    - List form (preferred): adds repo-specific dev-package names that
      don't have ABCI handlers (e.g. utility skills) on top of the
      auto-derived third-party ignores.
    - String form (legacy): used verbatim, REPLACING the auto-derive.
      Kept for backward compat with the e3dcda64-era trader/mech configs.
    """
    explicit = identity.get("check_handlers_ignores")
    if isinstance(explicit, str) and explicit.strip():
        return explicit
    auto_names = third_party_package_names(repo_root)
    extras: List[str] = []
    if isinstance(explicit, list):
        seen = set(auto_names)
        for name in explicit:
            if name not in seen:
                extras.append(name)
                seen.add(name)
    all_names = list(auto_names) + extras
    if not all_names:
        return ""
    return " ".join(f"-i {name}" for name in all_names)


def _resolve_check_dependencies_extra_excludes(identity: Dict[str, Any]) -> str:
    """`--exclude <pkg>` flags for `aea-helpers check-dependencies`.

    Accepts list or legacy string. Empty default — most repos don't need
    any excludes.
    """
    explicit = identity.get("check_dependencies_extra_excludes")
    if isinstance(explicit, list):
        return " ".join(f"--exclude {pkg}" for pkg in explicit)
    if isinstance(explicit, str):
        return explicit
    return ""


def _resolve_upstream_pins(
    autonomy_version: str, aea_version: str, identity: Dict[str, Any]
) -> str:
    """`--upstream <repo>@<version>` flags for `aea-ci check-third-party-hashes`.

    Always includes valory-xyz/open-autonomy and valory-xyz/open-aea pinned to
    the versions parsed from `[project].dependencies`. Consumers add
    additional non-PyPI upstreams (e.g. valory-xyz/mech-interact@0.28.0)
    via `[tool.tomte] upstream_pins` as a list or legacy string.
    """
    autoderive = [
        f"valory-xyz/open-autonomy@{autonomy_version}",
        f"valory-xyz/open-aea@{aea_version}",
    ]
    explicit = identity.get("upstream_pins")
    if isinstance(explicit, list):
        existing_repos = {p.split("@", 1)[0] for p in explicit}
        merged = [p for p in autoderive if p.split("@", 1)[0] not in existing_repos]
        merged.extend(explicit)
        return " ".join(f"--upstream {p}" for p in merged)
    if isinstance(explicit, str) and explicit.strip():
        # Legacy string form — assume the consumer included open-autonomy/aea.
        return explicit
    return " ".join(f"--upstream {p}" for p in autoderive)


def _render_gitleaks_merged(repo_root: Path, identity: Dict[str, Any]) -> str:
    """Build the merged gitleaks config: canonical base + repo allowlist.

    `[extend].path` references tomte's canonical gitleaks.toml so consumers
    inherit every rule. `[allowlist].paths` adds repo-specific path patterns
    (e.g. Vite UI bundle outputs that trip generic-api-key on every build).
    """
    extra_paths_raw = identity.get("gitleaks_extra_paths") or []
    if isinstance(extra_paths_raw, str):
        extra_paths = [extra_paths_raw]
    else:
        extra_paths = list(extra_paths_raw)
    base_path = str(GITLEAKS_TOML)
    if not extra_paths:
        return (
            "[extend]\n"
            "useDefault = false\n"
            f'path = "{base_path}"\n'
        )
    indented = ",\n".join(f"    '''{p}'''" for p in extra_paths)
    return (
        "[extend]\n"
        "useDefault = false\n"
        f'path = "{base_path}"\n'
        "\n"
        "[allowlist]\n"
        f'description = "{repo_root.name} overrides"\n'
        "paths = [\n"
        f"{indented}\n"
        "]\n"
    )


def _build_substitutions(
    repo_root: Path,
    pyproject: Dict[str, Any],
    identity: Dict[str, Any],
    extensions: Dict[str, str],
) -> Dict[str, str]:
    pkg_paths = _detect_packages_paths(repo_root, identity)
    skills_paths = identity.get("skills_paths") or f"{pkg_paths}/skills"

    autonomy_version, aea_version = _resolve_versions(pyproject, identity)

    upstream_pins = _resolve_upstream_pins(autonomy_version, aea_version, identity)

    service_public_id = (
        identity.get("service_public_id")
        or discover_service_public_id(repo_root)
        or ""
    )

    pytest_targets = _resolve_pytest_targets(repo_root, identity)
    service_specific_packages = _resolve_service_specific_packages(
        repo_root, identity
    )

    return {
        "TOMTE_VERSION": __version__,
        "TOMTE_DEP_PIN": _resolve_tomte_dep_pin(identity),
        "OPEN_AUTONOMY_VERSION": autonomy_version,
        "OPEN_AEA_VERSION": aea_version,
        "PACKAGES_PATHS": pkg_paths,
        "SKILLS_PATHS": skills_paths,
        "SERVICE_SPECIFIC_PACKAGES": _join_listish(service_specific_packages),
        "KNOWN_FIRST_PARTY": _KNOWN_FIRST_PARTY,
        "SERVICE_PUBLIC_ID": service_public_id,
        "PYTEST_TARGETS": _join_listish(pytest_targets),
        "UPSTREAM_PINS": upstream_pins,
        "CHECK_HANDLERS_IGNORES": _resolve_check_handlers_ignores(
            repo_root, identity
        ),
        "CHECK_DEPENDENCIES_EXTRA_EXCLUDES": _resolve_check_dependencies_extra_excludes(
            identity
        ),
        "EXTRA_DEPS_PACKAGES": _reindent(
            _resolve_extra_deps(pyproject, extensions), _DEPS_INDENT
        ),
        "EXTRA_TESTENVS": extensions.get("_raw_passthrough", ""),
        "EXTRA_PYLINT_FLAGS": _render_pylint_flags(extensions, identity),
    }


def _render(
    repo_root: Path,
    pyproject: Dict[str, Any],
    identity: Dict[str, Any],
    extensions: Dict[str, str],
) -> str:
    template_text = TOX_INI.read_text(encoding="utf-8")
    substitutions = _build_substitutions(repo_root, pyproject, identity, extensions)
    try:
        return Template(template_text).substitute(substitutions)
    except KeyError as exc:
        raise click.UsageError(
            f"Canonical tox.ini references unknown variable {exc.args[0]!r}."
        ) from exc


@click.command(
    name="tox",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.option(
    "--repo-root",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=Path.cwd(),
    help="Repo to operate on (default: CWD).",
)
@click.option(
    "--show",
    is_flag=True,
    default=False,
    help="Print rendered tox.ini to stdout instead of running tox.",
)
@click.argument("tox_args", nargs=-1, type=click.UNPROCESSED)
def tomte_tox(repo_root: Path, show: bool, tox_args: Tuple[str, ...]) -> None:
    """Run tox against tomte's canonical config, layered with this repo's pyproject + extensions.

    Reads `[tool.tomte]` from `<repo-root>/pyproject.toml` and (if a local
    `tox.ini` exists, or `local_extensions` is set explicitly) the
    `[tomte-extensions]` section from it. Renders tomte's canonical tox.ini
    into a temp file in the repo root, writes companion `.darglint` /
    `.gitleaks-merged.toml` files the canonical envs reference, then invokes
    `tox -c <temp> <tox_args>`.
    """
    repo_root = repo_root.resolve()
    pyproject = _read_pyproject(repo_root)
    identity = _read_tomte_section(pyproject)
    local_extensions_path = _detect_local_extensions(repo_root, identity)
    extensions = _read_local_extensions(repo_root, local_extensions_path)
    rendered = _render(repo_root, pyproject, identity, extensions)

    if show:
        click.echo(rendered)
        return

    rendered_path = repo_root / _RENDERED_TOX_FILENAME
    darglint_path = repo_root / _RENDERED_DARGLINT_FILENAME
    gitleaks_path = repo_root / _RENDERED_GITLEAKS_FILENAME
    rendered_path.write_text(rendered, encoding="utf-8")
    darglint_existed = darglint_path.exists()
    gitleaks_existed = gitleaks_path.exists()
    if not darglint_existed:
        darglint_path.write_text(_DARGLINT_CONFIG, encoding="utf-8")
    if not gitleaks_existed:
        gitleaks_path.write_text(
            _render_gitleaks_merged(repo_root, identity), encoding="utf-8"
        )
    try:
        cmd = ["tox", "-c", str(rendered_path)] + list(tox_args)
        result = subprocess.run(cmd, cwd=repo_root, check=False)
        sys.exit(result.returncode)
    finally:
        for path, written in [
            (rendered_path, True),
            (darglint_path, not darglint_existed),
            (gitleaks_path, not gitleaks_existed),
        ]:
            if not written:
                continue
            try:
                path.unlink()
            except OSError:
                pass
