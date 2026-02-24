import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.request import urlopen

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

PYPROJECT_PATH = Path("pyproject.toml")
INIT_PATH = Path("tomte/__init__.py")
TEST_PATH = Path("tests/test_tomte.py")


def load_dependencies() -> Tuple[Dict, Dict]:
    with PYPROJECT_PATH.open("rb") as file:
        config = tomllib.load(file)
    deps = config["tool"]["poetry"]["dependencies"]
    return config, deps


def extract_lowest_python_version(python_constraint: str) -> str:
    match = re.search(r">=\s*([0-9]+(?:\.[0-9]+){1,2})", python_constraint)
    if not match:
        raise ValueError(
            f"Cannot infer minimum Python version from constraint: {python_constraint}"
        )
    return match.group(1)


def release_supports_python(release_files: Iterable[Dict], python_version: str) -> bool:
    for file_info in release_files:
        if file_info.get("yanked"):
            continue
        requires_python = file_info.get("requires_python")
        if requires_python is None:
            return True
        try:
            if SpecifierSet(requires_python).contains(python_version, prereleases=True):
                return True
        except Exception:
            continue
    return False


def resolve_compatible_versions(package_name: str, python_version: str) -> List[str]:
    with urlopen(f"https://pypi.org/pypi/{package_name}/json", timeout=30) as response:
        payload = json.load(response)
    releases = payload.get("releases", {})
    candidates = []

    for raw_version, release_files in releases.items():
        if not release_files:
            continue
        try:
            parsed_version = Version(raw_version)
        except InvalidVersion:
            continue
        if parsed_version.is_prerelease:
            continue
        if not release_supports_python(release_files, python_version):
            continue
        candidates.append(parsed_version)

    sorted_versions = sorted(candidates, reverse=True)
    return [str(version) for version in sorted_versions]


def run_command(command: Iterable[str], dry_run: bool, check: bool = True):
    rendered = " ".join(command)
    print(f"$ {rendered}")
    if dry_run:
        return None
    return subprocess.run(command, check=check, capture_output=True, text=True)


def resolve_optional_extra_name(config: Dict, dependency_name: str) -> Optional[str]:
    extras = config.get("tool", {}).get("poetry", {}).get("extras", {})
    matches = [
        extra_name
        for extra_name, extra_deps in extras.items()
        if dependency_name in extra_deps
    ]
    if not matches:
        return None
    if dependency_name in matches:
        return dependency_name
    return matches[0]


def set_dependency_version(
    dependency_name: str,
    dependency_meta: Dict,
    candidate_versions: List[str],
    optional_extra_name: Optional[str],
    dry_run: bool,
) -> bool:
    current_spec = dependency_meta["version"]
    optional_flag = []
    if dependency_meta.get("optional"):
        if optional_extra_name is not None:
            optional_flag = [f"--optional={optional_extra_name}"]
        else:
            optional_flag = []

    if dry_run:
        if not candidate_versions:
            print(
                f"Skipping {dependency_name}: no compatible non-pre-release versions found (keeping {current_spec})"
            )
            return True
        target_spec = f"=={candidate_versions[0]}"
        print(f"Updating {dependency_name}: {current_spec} -> {target_spec}")
        run_command(
            ["poetry", "add", f"{dependency_name}@{target_spec}", *optional_flag],
            dry_run=True,
        )
        return True

    for candidate_version in candidate_versions:
        target_spec = f"=={candidate_version}"
        print(f"Trying {dependency_name}: {current_spec} -> {target_spec}")
        result = run_command(
            ["poetry", "add", f"{dependency_name}@{target_spec}", *optional_flag],
            dry_run=False,
            check=False,
        )
        if result.returncode == 0:
            print(f"Selected {dependency_name}={target_spec}")
            return True

        if result.stderr:
            stderr_lines = [line for line in result.stderr.strip().splitlines() if line]
            if stderr_lines:
                print(f"poetry error: {stderr_lines[-1]}")

        print(
            f"Rejected {dependency_name}={target_spec} by resolver. Trying next compatible version."
        )

    print(
        f"Failed to update {dependency_name}: no compatible candidate resolved via Poetry (kept {current_spec})."
    )
    return False


def bump_version(current_version: str, part: str) -> str:
    major, minor, patch = [int(chunk) for chunk in current_version.split(".")]
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return current_version


def replace_first(pattern: str, replacement: str, text: str, file_path: Path) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"Could not update expected pattern in {file_path}")
    return updated


def sync_package_version(new_version: str, dry_run: bool) -> None:
    pyproject_content = PYPROJECT_PATH.read_text(encoding="utf-8")
    pyproject_updated = replace_first(
        r'^version\s*=\s*"[^"]+"\s*$',
        f'version = "{new_version}"',
        pyproject_content,
        PYPROJECT_PATH,
    )

    init_content = INIT_PATH.read_text(encoding="utf-8")
    init_updated = replace_first(
        r'^__version__\s*=\s*"[^"]+"\s*$',
        f'__version__ = "{new_version}"',
        init_content,
        INIT_PATH,
    )

    test_content = TEST_PATH.read_text(encoding="utf-8")
    test_updated = replace_first(
        r'^\s*assert\s+__version__\s*==\s*"[^"]+"\s*$',
        f'    assert __version__ == "{new_version}"',
        test_content,
        TEST_PATH,
    )

    if dry_run:
        print(f"Would set package version to {new_version} in {PYPROJECT_PATH}, {INIT_PATH}, {TEST_PATH}")
        return

    PYPROJECT_PATH.write_text(pyproject_updated, encoding="utf-8")
    INIT_PATH.write_text(init_updated, encoding="utf-8")
    TEST_PATH.write_text(test_updated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bump optional dependencies to latest compatible versions and sync package version."
    )
    parser.add_argument(
        "--bump-version",
        choices=["none", "patch", "minor", "major"],
        default="patch",
        help="How to bump package version across pyproject, tomte/__init__.py and tests.",
    )
    parser.add_argument(
        "--no-lock",
        action="store_true",
        help="Skip running poetry lock at the end.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without changing files.",
    )
    args = parser.parse_args()

    config, deps = load_dependencies()
    minimum_python = extract_lowest_python_version(deps["python"])
    print(f"Using minimum supported Python version: {minimum_python}")

    optional_extra_map = {}
    for dependency_name, dependency_meta in deps.items():
        if dependency_name == "python":
            continue
        if not isinstance(dependency_meta, dict):
            continue
        optional_extra_map[dependency_name] = resolve_optional_extra_name(
            config=config,
            dependency_name=dependency_name,
        )

    dependency_info = {}
    for dependency_name, dependency_meta in deps.items():
        if dependency_name == "python":
            continue
        if not isinstance(dependency_meta, dict) or "version" not in dependency_meta:
            continue
        candidate_versions = resolve_compatible_versions(dependency_name, minimum_python)
        dependency_info[dependency_name] = {
            "meta": dependency_meta,
            "candidates": candidate_versions,
        }

    pending = list(dependency_info.keys())
    while pending:
        next_pending = []
        resolved_in_pass = 0
        for dependency_name in pending:
            info = dependency_info[dependency_name]
            updated = set_dependency_version(
                dependency_name=dependency_name,
                dependency_meta=info["meta"],
                candidate_versions=info["candidates"],
                optional_extra_name=optional_extra_map.get(dependency_name),
                dry_run=args.dry_run,
            )
            if updated:
                resolved_in_pass += 1
            else:
                next_pending.append(dependency_name)

        if not next_pending:
            break
        if resolved_in_pass == 0:
            unresolved = ", ".join(next_pending)
            raise RuntimeError(
                "Unable to resolve compatible versions automatically for: "
                f"{unresolved}"
            )
        print(
            "Retrying unresolved dependencies after graph updates: "
            f"{', '.join(next_pending)}"
        )
        pending = next_pending

    if args.bump_version != "none":
        current_version = config["tool"]["poetry"]["version"]
        new_version = bump_version(current_version, args.bump_version)
        print(f"Bumping package version: {current_version} -> {new_version}")
        sync_package_version(new_version, dry_run=args.dry_run)

    if not args.no_lock:
        run_command(["poetry", "lock"], dry_run=args.dry_run)


if __name__ == "__main__":
    main()
