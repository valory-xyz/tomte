#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2023 Valory AG
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

"""
This script checks that all the Python files of the repository have the copyright notice.

In particular:
- (optional) the Python shebang
- the encoding header;
- the copyright and license notices;

It is assumed the script is run from the repository root.
"""

import itertools
import re
import shutil
import subprocess  # nosec
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, Optional, Set, Tuple, cast

BIRTH_YEAR = 2021
CURRENT_YEAR = datetime.now().year
GIT_PATH = shutil.which("git")
START_YEARS = tuple(range(BIRTH_YEAR, datetime.today().year + 1))
# Broader range for secondary/historical authors (e.g. Fetch.AI Limited)
START_YEARS_HISTORICAL = tuple(range(2018, datetime.today().year + 1))
SHEBANG = "#!/usr/bin/env python3"

# Default regex for a single-author header (Valory AG)
HEADER_REGEX = re.compile(
    r"""(#!/usr/bin/env python3
)?# -\*- coding: utf-8 -\*-
# ------------------------------------------------------------------------------
#
#   Copyright ((20\d\d)(-20\d\d)?) Valory AG
#
#   Licensed under the Apache License, Version 2\.0 \(the \"License\"\);
#   you may not use this file except in compliance with the License\.
#   You may obtain a copy of the License at
#
#       http://www\.apache\.org/licenses/LICENSE-2\.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an \"AS IS\" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied\.
#   See the License for the specific language governing permissions and
#   limitations under the License\.
#
# ------------------------------------------------------------------------------
""",
    re.MULTILINE,
)


def _build_multi_author_header_regex(authors: Tuple[str, ...]) -> re.Pattern:
    """Build a header regex that matches multiple copyright lines.

    This builder is for multi-author headers only (2+ authors).
    For single-author, use the default HEADER_REGEX.

    :param authors: tuple of author names (must have len >= 2).
    :return: compiled regex pattern.
    """
    single_line = (
        r"#   Copyright (?:(?:20\d\d)(?:-20\d\d)?) (?:"
        + "|".join(re.escape(a) for a in authors)
        + r")"
    )
    copyright_pattern = r"(" + single_line + r"\n)+" + r"(?=#\n)"
    return re.compile(
        r"(#!/usr/bin/env python3\n)?# -\*- coding: utf-8 -\*-\n"
        r"# ------------------------------------------------------------------------------\n"
        r"#\n"
        + copyright_pattern
        + r"\n?"
        r"#\n"
        r"#   Licensed under the Apache License, Version 2\.0 \(the \"License\"\);\n"
        r"#   you may not use this file except in compliance with the License\.\n"
        r"#   You may obtain a copy of the License at\n"
        r"#\n"
        r"#       http://www\.apache\.org/licenses/LICENSE-2\.0\n"
        r"#\n"
        r"#   Unless required by applicable law or agreed to in writing, software\n"
        r"#   distributed under the License is distributed on an \"AS IS\" BASIS,\n"
        r"#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied\.\n"
        r"#   See the License for the specific language governing permissions and\n"
        r"#   limitations under the License\.\n"
        r"#\n"
        r"# ------------------------------------------------------------------------------\n",
        re.MULTILINE,
    )


# Regex to extract year data from any copyright line
COPYRIGHT_LINE_REGEX = re.compile(
    r"#   Copyright ((20\d\d)(-20\d\d)?) (.+)"
)
HEADER_TEMPLATE = """# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
{copyright_string}
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
"""


class ErrorTypes:  # pylint: disable=too-few-public-methods
    """Types of corrupt headers."""

    NO_ERROR = 0
    START_YEAR_NOT_ALLOWED = 1
    START_YEAR_GT_END_YEAR = 2
    END_YEAR_WRONG = 3
    END_YEAR_MISSING = 4


def get_modification_date(file: Path) -> datetime:
    """Returns modification date for the file."""
    (
        date_string,
        _,
    ) = subprocess.Popen(  # nosec  # pylint: disable=consider-using-with
        [str(GIT_PATH), "log", "-1", '--format="%ad"', "--", str(file)],
        stdout=subprocess.PIPE,
    ).communicate()
    date_string_ = date_string.decode().strip()
    if date_string_ == "":
        return datetime.now()
    return datetime.strptime(date_string_, '"%a %b %d %X %Y %z"')


def get_year_data(match: re.Match) -> Tuple[int, Optional[int]]:
    """Get year data from match."""
    _, year_string, *_ = match.groups()
    if "-" in year_string:
        return (*map(int, year_string.split("-")),)  # type: ignore
    return int(year_string), None


def _validate_years(
    file: Path,
    allowed_start_years: Tuple[int, ...],
    start_year: int,
    end_year: int,
    check_end_year: bool = True,
) -> Dict:
    """
    Given a file, check if the header stuff is in place.

    Return True if the files has the encoding header and the copyright notice,
    optionally prefixed by the shebang. Return False otherwise.

    :param file: the file to check.
    :param allowed_start_years: list of allowed start years
    :param start_year: year when the file was created
    :param end_year: year when the file was last modified
    :param check_end_year: whether to validate end year or not
    :return: True if the file is compliant with the checks, False otherwise.
    """

    modification_date = get_modification_date(file)
    check_info = {
        "check": True,
        "message": f"Start year {start_year} is not in the list of allowed years; {allowed_start_years}.",
        "start_year": start_year,
        "end_year": end_year,
        "last_modification": modification_date,
        "error_code": ErrorTypes.NO_ERROR,
    }

    # Start year is not in allowed start years list
    if start_year not in allowed_start_years:
        check_info["check"] = False
        check_info[
            "message"
        ] = f"Start year {start_year} is not in the list of allowed years; {allowed_start_years}."
        check_info["error_code"] = ErrorTypes.START_YEAR_NOT_ALLOWED
        return check_info

    # Specified year is 2021 but the file has been last modified in another later year (missing -202x)
    if end_year is not None and check_end_year:

        if start_year > end_year:
            check_info["check"] = False
            check_info["message"] = "End year should be greater then start year."
            check_info["error_code"] = ErrorTypes.START_YEAR_GT_END_YEAR
            return check_info

        if end_year != modification_date.year:
            check_info["check"] = False
            check_info[
                "message"
            ] = f"End year does not match the last modification year. Header has: {end_year}; Last Modified: {modification_date.year}"
            check_info["error_code"] = ErrorTypes.END_YEAR_WRONG
            return check_info

    if end_year is None and check_end_year and modification_date.year > start_year:
        check_info["check"] = False
        check_info["message"] = f"Missing later year ({start_year}-20..)"
        check_info["error_code"] = ErrorTypes.END_YEAR_MISSING
        return check_info

    return check_info


def fix_header(check_info: Dict) -> bool:
    """Fix corrupt headers.

    Only supports single-author (Valory AG) headers.
    Multi-author fix mode is not supported.
    """

    path = cast(Path, check_info.get("path"))
    content = path.read_text()
    copyright_string = ""
    is_update_needed = False
    missing_header = False

    if "error_code" not in check_info:
        copyright_string = "#   Copyright {start_year}-{end_year} Valory AG".format(
            start_year=BIRTH_YEAR,
            end_year=get_modification_date(path).year,
        )
        missing_header = True

    elif check_info["error_code"] in (
        ErrorTypes.END_YEAR_WRONG,
        ErrorTypes.END_YEAR_MISSING,
    ):
        copyright_string = "#   Copyright {start_year}-{end_year} Valory AG".format(
            start_year=check_info["start_year"],
            end_year=check_info["last_modification"].year,
        )
        is_update_needed = True

    elif check_info["error_code"] == ErrorTypes.START_YEAR_GT_END_YEAR:
        copyright_string = "#   Copyright {end_year}-{start_year} Valory AG".format(
            start_year=check_info["start_year"],
            end_year=check_info["last_modification"].year,
        )
        is_update_needed = True

    if missing_header:
        new_header = HEADER_TEMPLATE.format(copyright_string=copyright_string)
        new_header = SHEBANG + "\n" + new_header
        if content != "":
            new_header += "\n\n"
        updated_content = new_header + content
        path.write_text(updated_content)
        return True

    if is_update_needed:
        new_header = HEADER_TEMPLATE.format(copyright_string=copyright_string)
        if SHEBANG in content:
            new_header = SHEBANG + "\n" + new_header
        updated_content = HEADER_REGEX.sub(new_header, content)
        path.write_text(updated_content)

    return is_update_needed


def update_headers(files: Iterator[Path]) -> None:
    """Update headers (single-author mode only)."""

    needs_update = []

    for path in files:
        print("Checking {}".format(path))
        check_data = check_copyright(path)
        if not check_data["check"]:
            check_data["path"] = path
            needs_update.append(check_data)

    if len(needs_update) > 0:
        print("\n\nUpdating headers.\n")
        cannot_update = []
        for check_data in needs_update:
            print("Updating {}".format(check_data["path"]))
            if not fix_header(check_data):
                cannot_update.append(check_data)

        if len(cannot_update) > 0:
            print("\nFollowing files were not updated.\n")
            print("\n".join([str(check_data["path"]) for check_data in cannot_update]))
    else:
        print("No update needed.")


def check_copyright(file: Path, authors: Optional[Tuple[str, ...]] = None) -> Dict:
    """
    Given a file, check if the header stuff is in place.

    Return True if the files has the encoding header and the copyright notice,
    optionally prefixed by the shebang. Return False otherwise.

    :param file: the file to check.
    :param authors: tuple of allowed author names. If None, uses default single-author regex.
    :return: True if the file is compliant with the checks, False otherwise.
    """
    content = file.read_text()

    if authors is not None and len(authors) > 1:
        # Multi-author: validate that the header structure is correct,
        # then check years on the primary author's copyright line only.
        # Secondary (historical) authors are accepted as-is.
        header_regex = _build_multi_author_header_regex(authors)
        match = header_regex.match(content)
        if match is None:
            return {"check": False, "message": "Invalid copyright header."}

        primary_author = authors[0]
        primary_result = None
        last_secondary_result = None
        for line_match in COPYRIGHT_LINE_REGEX.finditer(match.group(0)):
            line_author = line_match.group(4).strip()
            year_string = line_match.group(1)
            if "-" in year_string:
                start_year, end_year = map(int, year_string.split("-"))
            else:
                start_year, end_year = int(year_string), None

            if line_author == primary_author:
                primary_result = _validate_years(
                    file, START_YEARS, start_year, end_year
                )
                if not primary_result["check"]:
                    return primary_result
            else:
                # Secondary (historical) authors: validate against broader
                # year range, matching open-aea's behavior for FetchAI files
                last_secondary_result = _validate_years(
                    file, START_YEARS_HISTORICAL, start_year, end_year,
                    check_end_year=False,
                )
                if not last_secondary_result["check"]:
                    return last_secondary_result

        # If the primary author was found, return its validation result.
        # If only secondary (historical) authors are present, return their result.
        if primary_result is not None:
            return primary_result
        if last_secondary_result is not None:
            return last_secondary_result
    else:
        match = HEADER_REGEX.match(content)
        if match is not None:
            return _validate_years(file, START_YEARS, *get_year_data(match))  # type: ignore

    return {"check": False, "message": "Invalid copyright header."}


def run_check(
    files: Iterator[Path],
    authors: Optional[Tuple[str, ...]] = None,
) -> None:
    """Run copyright check.

    :param files: iterator of file paths to check.
    :param authors: tuple of allowed author names, or None for single-author default.
    """
    bad_files = set()
    for path in files:
        print("Processing {}".format(path))
        check_data = check_copyright(path, authors=authors)
        if not check_data["check"]:
            bad_files.add((path, check_data["message"]))

    if len(bad_files) > 0:
        print("The following files are not well formatted:")
        print(
            "\n".join(
                map(
                    lambda x: f"File: {x[0]}\nReason: {x[1]}\n",
                    sorted(bad_files, key=lambda x: x[0]),
                )
            )
        )
        sys.exit(1)
    else:
        print("OK")
        sys.exit(0)


def main(
    authors: Tuple[str, ...],
    exclude_parts: Set[str],
    fix: bool = False,
    scan_paths: Optional[Tuple[str, ...]] = None,
) -> None:
    """Main function.

    :param authors: tuple of author names. First author is the primary (used for fix mode
        and year validation). Additional authors are accepted as historical.
    :param exclude_parts: set of path parts to exclude.
    :param fix: whether to fix headers or just check.
    :param scan_paths: custom paths to scan. If None, uses default (packages/{author}, tests, scripts).
    """

    if fix and len(authors) > 1:
        print(
            "Error: fix mode is not supported with multiple authors. "
            "Multi-author headers contain historical copyright lines that "
            "should not be auto-modified.",
            file=sys.stderr,
        )
        sys.exit(1)

    primary_author = authors[0]
    exclude_files = {Path("scripts", "whitelist.py")}

    if scan_paths:
        path_tuples = [tuple(p.split("/")) for p in scan_paths]
    else:
        path_tuples = [("packages", primary_author), ("tests",), ("scripts",)]

    python_files = filter(
        lambda x: x not in exclude_files,
        itertools.chain(
            *(
                Path(*path).glob("**/*.py")
                for path in path_tuples
            )
        ),
    )

    def _file_filter(file: Path) -> bool:
        """Filter for files."""
        file_str = str(file)
        unwanted_parts = {
            "t_protocol",
            "t_protocol_no_ct",
            "build",
        }.union(exclude_parts)

        # protocols are generated using generate_all_protocols.py
        return (
            not file_str.endswith("_pb2.py")
            and not file_str.endswith("_pb2_grpc.py")
            and not any(part in file.parts for part in unwanted_parts)
        )

    python_files_filtered = filter(_file_filter, python_files)
    authors_tuple = authors if len(authors) > 1 else None
    if fix:
        update_headers(python_files_filtered)
    else:
        run_check(python_files_filtered, authors=authors_tuple)
