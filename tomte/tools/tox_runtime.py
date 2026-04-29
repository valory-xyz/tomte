"""`tomte tox` — runtime wrapper that runs tox against tomte's canonical config.

Replaces the older `tomte scaffold tox` flow that copied a 500+ line tox.ini
into every consuming repo. Instead, the canonical tox.ini lives only in
tomte; consuming repos carry only their identity (a small `[tool.tomte]`
section in pyproject.toml) and, in rare cases, a small `[tomte-extensions]`
section in a local `tox.ini` for things that don't fit cleanly in TOML
(extra deps with version pins, pylint extras, mypy per-package overrides).

The wrapper reads pyproject + (optional) local extensions, renders tomte's
canonical tox.ini into a temp file in the repo root, and invokes
`tox -c <temp-file> <args>`.
"""

from __future__ import annotations

import configparser
import os
import subprocess
import sys
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

try:
    import tomllib
except ImportError:  # py3.10
    import tomli as tomllib  # type: ignore[no-redef]

import click

from tomte import __version__
from tomte.configs import TOX_INI


_REQUIRED_KEYS: Tuple[str, ...] = (
    "packages_paths",
    "pytest_targets",
    "service_specific_packages",
    "service_public_id",
    "known_first_party",
    "open_autonomy_version",
    "open_aea_version",
)

# Multi-line continuation values need re-indenting after configparser strip.
_DEPS_INDENT = 4

# Filename for the rendered tox.ini in the consuming repo. Hidden so a
# stray `ls` doesn't surprise people; deterministic so the wrapper can
# overwrite cleanly across runs.
_RENDERED_TOX_FILENAME = ".tomte-tox.ini"


def _read_pyproject_tomte(repo_root: Path) -> Dict[str, Any]:
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.is_file():
        raise click.UsageError(f"No pyproject.toml at {pyproject_path}")
    with pyproject_path.open("rb") as fh:
        data = tomllib.load(fh)
    section = data.get("tool", {}).get("tomte", {})
    if not section:
        raise click.UsageError(
            "Missing [tool.tomte] section in pyproject.toml. "
            "See `tomte tox --help` for the schema."
        )
    return section


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
# is copied verbatim into the rendered output.
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


def _render_pylint_flags(extensions: Dict[str, str]) -> str:
    flags: List[str] = []
    raw_modules = extensions.get("extra_pylint_ignored_modules", "").strip()
    if raw_modules:
        flags.append(f"--ignored-modules={raw_modules}")
    raw_disables = extensions.get("extra_pylint_disables", "").strip()
    if raw_disables:
        flags.append(f"--disable={raw_disables}")
    return " ".join(flags)


def _join_listish(value: Union[str, Sequence[str]]) -> str:
    if isinstance(value, str):
        return value
    return " ".join(value)


def _build_substitutions(
    identity: Dict[str, Any], extensions: Dict[str, str]
) -> Dict[str, str]:
    missing = [k for k in _REQUIRED_KEYS if not identity.get(k)]
    if missing:
        raise click.UsageError(
            "[tool.tomte] is missing required keys: " + ", ".join(missing)
        )

    pkg_paths = identity["packages_paths"]
    skills_paths = identity.get("skills_paths") or f"{pkg_paths}/skills"

    upstream_pins = identity.get("upstream_pins") or (
        f"--upstream valory-xyz/open-autonomy@{identity['open_autonomy_version']} "
        f"--upstream valory-xyz/open-aea@{identity['open_aea_version']}"
    )

    return {
        "TOMTE_VERSION": __version__,
        "TOMTE_DEP_PIN": identity.get("tomte_dep_pin", f"=={__version__}"),
        "OPEN_AUTONOMY_VERSION": identity["open_autonomy_version"],
        "OPEN_AEA_VERSION": identity["open_aea_version"],
        "PACKAGES_PATHS": pkg_paths,
        "SKILLS_PATHS": skills_paths,
        "SERVICE_SPECIFIC_PACKAGES": _join_listish(identity["service_specific_packages"]),
        "KNOWN_FIRST_PARTY": identity["known_first_party"],
        "SERVICE_PUBLIC_ID": identity["service_public_id"],
        "PYTEST_TARGETS": _join_listish(identity["pytest_targets"]),
        "UPSTREAM_PINS": upstream_pins,
        "CHECK_HANDLERS_IGNORES": identity.get("check_handlers_ignores", ""),
        "CHECK_DEPENDENCIES_EXTRA_EXCLUDES": identity.get(
            "check_dependencies_extra_excludes", ""
        ),
        "EXTRA_DEPS_PACKAGES": _reindent(extensions.get("extra_deps", ""), _DEPS_INDENT),
        "EXTRA_TESTENVS": extensions.get("_raw_passthrough", ""),
        "EXTRA_PYLINT_FLAGS": _render_pylint_flags(extensions),
    }


def _render(identity: Dict[str, Any], extensions: Dict[str, str]) -> str:
    template_text = TOX_INI.read_text(encoding="utf-8")
    substitutions = _build_substitutions(identity, extensions)
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

    Reads `[tool.tomte]` from `<repo-root>/pyproject.toml` and (if
    `local_extensions` is set) `[tomte-extensions]` from the named local
    tox.ini. Renders tomte's canonical tox.ini into a temp file in the
    repo root, then invokes `tox -c <temp> <tox_args>`.
    """
    repo_root = repo_root.resolve()
    identity = _read_pyproject_tomte(repo_root)
    extensions = _read_local_extensions(repo_root, identity.get("local_extensions"))
    rendered = _render(identity, extensions)

    if show:
        click.echo(rendered)
        return

    rendered_path = repo_root / _RENDERED_TOX_FILENAME
    rendered_path.write_text(rendered, encoding="utf-8")
    try:
        cmd = ["tox", "-c", str(rendered_path)] + list(tox_args)
        result = subprocess.run(cmd, cwd=repo_root, check=False)
        sys.exit(result.returncode)
    finally:
        try:
            rendered_path.unlink()
        except OSError:
            pass
