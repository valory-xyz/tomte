from pathlib import Path
from typing import List, Optional, Tuple

import click

from tomte import __version__
from tomte.tools.check_copyright import main as check_copyright_main
from tomte.tools.check_doc_links import main as check_doc_links_main
from tomte.tools.check_readme import main as check_readme_main
from tomte.tools.freeze_dependencies import main as freeze_dependencies_main
from tomte.tools.freeze_gitleaks import main as freeze_gitleaks_main
from tomte.tools.render_isort_config import main as render_isort_config_main
from tomte.tools.render_mypy_config import main as render_mypy_config_main
from tomte.tools.tox_runtime import tomte_tox


@click.group(name="tomte")  # type: ignore
@click.version_option(__version__, prog_name="tomte")
def cli() -> None:
    """Command-line tool for keeping Python projects clean."""


def _run_canonical_tox(args: Tuple[str, ...]) -> None:
    """Invoke `tomte tox` with the given args against the CWD.

    These shortcut commands (format-code, check-code, check-security) used to
    shell out to plain `tox` directly, which only sees the local tox.ini.
    Under the slim `[tomte-extensions]` overlay form, the lint/format envs
    live in tomte's bundled tox.ini and are merged in only by `tomte tox` —
    so plain `tox -e black-check` blew up with "environment not found".
    Routing through `tomte_tox.callback` reuses the same merge path the
    `tomte tox` CLI takes, fixing the slim-overlay case without breaking
    legacy hand-written tox.ini consumers (which still work because the
    canonical envs are identical there too).

    :param args: tox positional args (e.g. ``("-p", "-e", "black-check", ...)``).
    """
    # Click typing: `.callback` is `Optional[Callable]`; mypy can't prove non-None
    # post-decoration. Stripping the ignore here regresses `tox -e mypy`.
    tomte_tox.callback(  # type: ignore[misc]
        repo_root=Path.cwd(),
        show=False,
        tox_args=args,
    )


@click.command()
def format_code() -> None:
    """Run code formatters sequentially: isort and black."""
    _run_canonical_tox(("-e", "isort", "-e", "black"))


@click.command()
@click.option("--author", type=str, required=True, multiple=True, help="Author name(s) to accept in copyright headers.")
@click.option("--exclude-part", '-e', multiple=True)
@click.option("--scan-path", multiple=True, help="Paths to scan (overrides defaults).")
@click.option("--repo-root", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None,
              help="Directory containing packages/packages.json for third-party auto-exclude (default: cwd).")
def format_copyright(author: Tuple[str, ...], exclude_part: Tuple[str, ...], scan_path: Tuple[str, ...], repo_root: "Optional[Path]") -> None:
    """Run copyright formatter."""
    check_copyright_main(author, set(exclude_part), fix=True, scan_paths=scan_path, repo_root=repo_root)


@click.command()
def check_code() -> None:
    """Run code checks in parallel: black, isort, flake8, mypy, pylint, and darglint."""
    _run_canonical_tox(
        (
            "-p",
            "-e", "black-check",
            "-e", "isort-check",
            "-e", "flake8",
            "-e", "mypy",
            "-e", "pylint",
            "-e", "darglint",
        )
    )


@click.command()
def check_security() -> None:
    """Run security checks in parallel: safety and bandit."""
    _run_canonical_tox(("-p", "-e", "safety", "-e", "bandit"))


@click.command()
@click.option("--author", type=str, required=True, multiple=True, help="Author name(s) to accept in copyright headers.")
@click.option("--exclude-part", '-e', multiple=True)
@click.option("--scan-path", multiple=True, help="Paths to scan (overrides defaults).")
@click.option("--repo-root", type=click.Path(exists=True, file_okay=False, path_type=Path), default=None,
              help="Directory containing packages/packages.json for third-party auto-exclude (default: cwd).")
def check_copyright(author: Tuple[str, ...], exclude_part: Tuple[str, ...], scan_path: Tuple[str, ...], repo_root: "Optional[Path]") -> None:
    """Check copyright on all the files in a project."""
    check_copyright_main(author, set(exclude_part), scan_paths=scan_path, repo_root=repo_root)


@click.command()
@click.option(
    "--http-skips", "-n", multiple=True, help="Http urls to skip."
)
@click.option("--url-skips", "-u", multiple=True, help="Urls to skip.")
@click.option(
    "--check-internal", is_flag=True, default=False,
    help="Also validate internal doc links, anchors, and images.",
)
def check_doc_links(
    http_skips: Tuple[str, ...],
    url_skips: Tuple[str, ...],
    check_internal: bool,
) -> None:
    """Check doc links on all the doc .md files."""
    check_doc_links_main(http_skips, url_skips, check_internal=check_internal)


@click.command()
@click.option("--package-path", type=str, required=True)
def check_readme(package_path: str) -> None:
    """Check readme file."""
    check_readme_main(package_path)


@click.command()
@click.option("--output-path", type=str, required=False)
@click.option("--exclude-package", multiple=True, help="Package name(s) to exclude from output.")
def freeze_dependencies(output_path: Optional[str], exclude_package: Tuple[str, ...]) -> None:
    """Freeze dependencies."""
    freeze_dependencies_main(output_path=output_path, exclude_packages=exclude_package)


@click.command(name="render-isort-config")
@click.option("--output", required=True, type=click.Path(), help="Where to write the merged isort.cfg.")
@click.option("--known-first-party", default="", help="Per-repo `known_first_party` value.")
@click.option("--known-packages", default="", help="Per-repo `known_packages` value.")
@click.option("--known-local-folder", default="", help="Per-repo `known_local_folder` value.")
def render_isort_config(output: str, known_first_party: str, known_packages: str, known_local_folder: str) -> None:
    """Render tomte canonical isort.cfg + per-repo packaging keys to a merged file."""
    render_isort_config_main(
        output=output,
        known_first_party=known_first_party,
        known_packages=known_packages,
        known_local_folder=known_local_folder,
    )


@click.command(name="render-mypy-config")
@click.option("--output", required=True, type=click.Path(), help="Where to write the merged mypy.ini.")
@click.option("--append-from", default="", type=click.Path(), help="Path to ini file whose [mypy*] sections layer onto canonical.")
def render_mypy_config(output: str, append_from: str) -> None:
    """Render tomte canonical mypy.ini + an additional ini file's [mypy*] sections."""
    render_mypy_config_main(output=output, append_from=append_from)


@click.command(name="freeze-gitleaks")
@click.option("--output", default=".gitleaksignore", type=click.Path(), help="Where to write the .gitleaksignore.")
@click.option("--gitleaks-executable", default="gitleaks", help="gitleaks binary on PATH.")
def freeze_gitleaks(output: str, gitleaks_executable: str) -> None:
    """Run gitleaks against tomte canonical config and emit current findings as a baseline."""
    freeze_gitleaks_main(output=output, gitleaks_executable=gitleaks_executable)


cli.add_command(freeze_dependencies)
cli.add_command(format_copyright)
cli.add_command(format_code)
cli.add_command(check_code)
cli.add_command(check_copyright)
cli.add_command(check_doc_links)
cli.add_command(check_readme)
cli.add_command(check_security)
cli.add_command(render_isort_config)
cli.add_command(render_mypy_config)
cli.add_command(freeze_gitleaks)
cli.add_command(tomte_tox)


if __name__ == "__main__":
    cli()
