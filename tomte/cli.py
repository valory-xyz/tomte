import sys
from typing import List, Optional

import click
import subprocess
from pathlib import Path

from tox import cmdline as tox_cmdline

from tomte import __version__
from tomte.tools.check_copyright import main as check_copyright_main
from tomte.tools.check_doc_links import main as check_doc_links_main
from tomte.tools.check_readme import main as check_readme_main
from tomte.tools.freeze_dependencies import main as freeze_dependencies_main


@click.group(name="tomte")  # type: ignore
@click.version_option(__version__, prog_name="tomte")
def cli() -> None:
    """Command-line tool for keeping Python projects clean."""


@click.command()
def format_code() -> None:
    """Run code formatters sequentially: isort and black."""
    sys.argv = ["tox", "-e", "isort", "-e", "black"]
    tox_cmdline()


@click.command()
@click.option("--author", type=str, required=True)
@click.option("--exclude-part", '-e', multiple=True)
def format_copyright(author: str, exclude_part: List[str]) -> None:
    """Run copyright formatter."""
    check_copyright_main(author, set(exclude_part), fix=True)


@click.command()
def check_code() -> None:
    """Run code checks in parallel: black, isort, flake8, mypy, pylint, and darglint."""
    sys.argv = [
        "tox",
        "-p",
        "-e",
        "black-check",
        "-e",
        "isort-check",
        "-e",
        "flake8",
        "-e",
        "mypy",
        "-e",
        "pylint",
        "-e",
        "darglint",
    ]
    tox_cmdline()


@click.command()
def check_security() -> None:
    """Run security checks in parallel: safety and bandit."""
    sys.argv = ["tox", "-p", "-e", "safety", "-e", "bandit"]
    tox_cmdline()


@click.command()
@click.option("--author", type=str, required=True)
@click.option("--exclude-part", '-e', multiple=True)
def check_copyright(author: str, exclude_part: List[str]) -> None:
    """Check copyright on all the files in a project."""
    check_copyright_main(author, set(exclude_part))


@click.command()
@click.option(
    "--http-skips", "-n", multiple=True, default=None, help="Http urls to skip."
)
@click.option("--url-skips", "-n", multiple=True, default=None, help="Urls to skip.")
def check_doc_links(
    http_skips: Optional[List[str]] = None,
    url_skips: Optional[List[str]] = None,
) -> None:
    """Check doc links on all the doc .md files."""
    check_doc_links_main(http_skips, url_skips)


@click.command()
@click.option("--package-path", type=str, required=True)
def check_readme(package_path: str) -> None:
    """Check readme file."""
    check_readme_main(package_path)


@click.command()
@click.option("--output-path", type=str, required=False)
def freeze_dependencies(output_path: Optional[str]) -> None:
    """Freeze dependencies."""
    freeze_dependencies_main(output_path=output_path)

@click.command()
def check_spelling() -> None:
    """Check spelling on all the doc .md files."""
    script_path = Path(__file__).resolve()
    target_script = Path(script_path.parent, 'scripts', 'check_spelling.sh')
    subprocess.call(['sh', target_script])

cli.add_command(freeze_dependencies)
cli.add_command(format_copyright)
cli.add_command(format_code)
cli.add_command(check_code)
cli.add_command(check_copyright)
cli.add_command(check_doc_links)
cli.add_command(check_readme)
cli.add_command(check_security)
cli.add_command(check_spelling)


if __name__ == "__main__":
    cli()
