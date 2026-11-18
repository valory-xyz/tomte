"""Pin the released packages in a repo's lock for `safety check -r`."""

from __future__ import annotations

from pathlib import Path
from typing import List, Set, Tuple

import click

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


LOCKFILES = ("uv.lock", "poetry.lock")
# Lock sources (uv keys, poetry `type`s) that are local code, not a release.
_LOCAL_SOURCES = {"editable", "virtual", "directory", "path", "file"}
# Pinned like any release, so safety checks that version's PyPI release, not this source.
_UNPUBLISHED_SOURCES = {"git", "url"}


def export(repo_root: Path) -> Tuple[str, List[str]]:
    """Return the pins, and the names of packages locked from git or a URL."""
    lock_path = next(
        (repo_root / name for name in LOCKFILES if (repo_root / name).is_file()),
        None,
    )
    if lock_path is None:
        raise click.ClickException(
            f"No {' or '.join(LOCKFILES)} in {repo_root}; nothing to scan."
        )
    try:
        with lock_path.open("rb") as fh:
            lock = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise click.ClickException(f"Cannot read {lock_path}: {exc}") from exc
    pins: Set[str] = set()
    unpublished: Set[str] = set()
    for package in lock.get("package", []):
        source = package.get("source", {})
        kinds = {*source, source.get("type")}
        if _LOCAL_SOURCES & kinds or "name" not in package or "version" not in package:
            continue
        pins.add(f"{package['name']}=={package['version']}")
        if _UNPUBLISHED_SOURCES & kinds:
            unpublished.add(package["name"])
    return "".join(f"{pin}\n" for pin in sorted(pins)), sorted(unpublished)


def main(output_path: Path, repo_root: Path) -> None:
    """Write the pins to `output_path`, and name what they cannot cover."""
    pins, unpublished = export(repo_root)
    output_path.write_text(pins, encoding="utf-8")
    if unpublished:
        click.echo(
            "warning: locked from git or a URL, so safety checks the PyPI "
            f"release of the same version instead: {', '.join(unpublished)}",
            err=True,
        )
