#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022-2023 Valory AG
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

"""This module contains the tests for the links in the documentation."""


import re
import sys
import xml.etree.ElementTree as ET  # nosec
from concurrent.futures import ThreadPoolExecutor
from itertools import chain
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests
import urllib3  # type: ignore
from requests.adapters import HTTPAdapter  # type: ignore
from urllib3.util.retry import Retry  # type: ignore

# Disable insecure request warning (expired SSL certificates)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


MAX_WORKERS = 10
URL_REGEX = r'(https?:\/\/(?:www\.|(?!www))[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s)"]{2,}|www\.[a-zA-Z0-9][a-zA-Z0-9-]+[a-zA-Z0-9]\.[^\s)"]{2,}|https?:\/\/(?:www\.|(?!www))[a-zA-Z0-9]+\.[^\s)"]{2,}|www\.[a-zA-Z0-9]+\.[^\s)"]{2,})'
DEFAULT_REQUEST_TIMEOUT = 5  # seconds

# Allow some links to be HTTP because there is no HTTPS alternative
# Remove non-url-allowed characters like ` before adding them here
HTTP_SKIPS = [
    "http://www.fipa.org/repository/ips.php3",
    "http://host.docker.internal:8545",
]

# Special links that are allowed to respond with an error status
# Remove non-url-allowed characters like ` before adding them here
URL_SKIPS = [
    "https://gateway.autonolas.tech/ipfs/<hash>",  # non link (400)
    "https://github.com/valory-xyz/open-autonomy/trunk/infrastructure",  # svn link (404)
    "http://host.docker.internal:8545",  # internal (ERR_NAME_NOT_RESOLVED)
]

# Define here custom timeouts for some edge cases
CUSTOM_TIMEOUTS = {
    "http://www.fipa.org/repository/ips.php3": 30,
}


def read_file(filepath: str) -> str:
    """Loads a file into a string"""
    with open(filepath, "r", encoding="utf-8") as file_:
        file_str = file_.read()
    return file_str


def check_file(
    session: Any,
    md_file: str,
    http_skips: Optional[List[str]] = None,
    url_skips: Optional[List[str]] = None,
) -> Dict:
    """Check for broken or HTTP links in a specific file"""

    http_skips = http_skips or HTTP_SKIPS
    url_skips = url_skips or URL_SKIPS

    text = read_file(md_file)
    m = re.findall(URL_REGEX, text)
    http_links = []
    broken_links = []

    for url in m:

        # Add the closing parenthesis if it is missing, as the REGEX is too strict sometimes
        if "(" in url and ")" not in url:
            url += ")"

        # Remove non allowed chars
        url = url.replace("`", "")

        # Check for HTTP urls
        if not url.startswith("https") and url not in http_skips:
            http_links.append((md_file, url))

        # Check for url skips
        if url in url_skips:
            continue

        # Check for broken links: 200 and 403 codes are admitted
        try:
            # Use HEAD requests to avoid rate-limiting on content-heavy pages (e.g. GitHub blob URLs)
            # Fall back to GET if HEAD returns a non-success status
            # Do not verify requests. Expired SSL certificates would make those links fail
            request_kwargs = dict(
                timeout=CUSTOM_TIMEOUTS.get(url, DEFAULT_REQUEST_TIMEOUT),
                verify=False,
                allow_redirects=True,
            )
            status_code = session.head(url, **request_kwargs).status_code
            if status_code != 200:
                status_code = session.get(url, **request_kwargs).status_code
            if status_code not in [200, 403]:
                broken_links.append({"url": url, "status_code": status_code})
        except (
            requests.exceptions.RetryError,
            requests.exceptions.ConnectionError,
        ) as e:
            broken_links.append({"url": url, "status_code": e})

    return {
        "file": str(md_file),
        "http_links": http_links,
        "broken_links": broken_links,
    }


LINK_PATTERN_HTML = re.compile(r'(?<=<a href=")[^"]*')
# Negative lookbehind (?<!!) excludes markdown image syntax ![alt](path)
LINK_PATTERN_MD = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
MD_IMAGE_PATTERN = re.compile(r"!\[([^\]]+)\]\(([^)]+)\)")
IMAGE_PATTERN = re.compile(r'<img[^>]+src="([^">]+)"')
ANCHOR_TAG_PATTERN = re.compile(r"<a.*?>(.+?)</a>")
DOCS_DIR = Path("docs")


def _is_external_url(url: str) -> bool:
    """Check if a URL is external."""
    return url.startswith("https://") or url.startswith("http://")


def _check_internal_links(
    file: Path,
    all_docs_files: Set[Path],
) -> List[str]:
    """Check internal links in a documentation file.

    Validates:
    - HTML <a href="..."> and markdown [text](url) links point to existing doc files
    - Anchor fragments (#section) exist in target files (heuristic: substring match)
    - <img src="..."> images exist on disk
    - External <a> tags have target="_blank"

    :param file: path to the markdown file to check.
    :param all_docs_files: set of all documentation file paths.
    :return: list of error messages.
    """
    errors: List[str] = []
    text = file.read_text(encoding="utf-8")

    # Check HTML <a href="..."> links
    for match in LINK_PATTERN_HTML.finditer(text):
        url = match.group()
        if _is_external_url(url):
            continue
        try:
            _validate_internal_url(file, url, all_docs_files)
        except ValueError as e:
            errors.append(str(e))

    # Check markdown [text](url) links
    for match in LINK_PATTERN_MD.finditer(text):
        url = match.group(2).strip()
        if _is_external_url(url):
            continue
        if url.startswith("#"):
            # Same-file anchor — skip (would need heading parsing)
            continue
        try:
            _validate_internal_url(file, url, all_docs_files)
        except ValueError as e:
            errors.append(str(e))

    # Check HTML <img src="..."> and markdown ![alt](path) images
    for match in IMAGE_PATTERN.finditer(text):
        src = match.group(1)
        if _is_external_url(src):
            continue
        img_path = (file.parent / src).resolve()
        if not img_path.exists():
            errors.append(
                f"Image path={src} in file={file} not found!"
            )

    for match in MD_IMAGE_PATTERN.finditer(text):
        src = match.group(2).strip()
        if _is_external_url(src):
            continue
        img_path = (file.parent / src).resolve()
        if not img_path.exists():
            errors.append(
                f"Image path={src} in file={file} not found!"
            )

    # Check external <a> tags have target="_blank"
    for match in ANCHOR_TAG_PATTERN.finditer(text):
        try:
            tag = ET.fromstring(match.group())  # nosec
        except ET.ParseError:
            continue
        href = tag.attrib.get("href")
        target = tag.attrib.get("target")
        if href and _is_external_url(href) and target != "_blank":
            errors.append(
                f"External link href={href} in file={file} missing target=\"_blank\"."
            )

    return errors


def _validate_internal_url(
    file: Path,
    url: str,
    all_docs_files: Set[Path],
) -> None:
    """Validate an internal relative URL points to an existing doc file.

    Resolves the URL relative to the source file's parent directory.

    :param file: the source file.
    :param url: the relative URL to validate.
    :param all_docs_files: set of all doc file paths.
    :raises ValueError: if the link is invalid.
    """
    hash_index = url.find("#")
    if hash_index == 0:
        # Pure anchor link (#section) — skip
        return

    if hash_index != -1:
        path_part = url[:hash_index]
        anchor = url[hash_index:]
    else:
        path_part = url
        anchor = ""

    path_part = path_part.rstrip("/")

    # Resolve relative to source file's directory
    if path_part.endswith(".md"):
        target_path = (file.parent / path_part).resolve()
    else:
        target_path = (file.parent / f"{path_part}.md").resolve()

    # Normalize to project-relative for comparison with all_docs_files
    try:
        target_relative = target_path.relative_to(Path.cwd())
    except ValueError:
        raise ValueError(
            f"Path={url} in file={file} resolves outside project root!"
        )

    if target_relative not in all_docs_files:
        raise ValueError(
            f"Path={target_relative} found in file={file} does not exist!"
        )

    if anchor:
        # Heuristic: check if the anchor string appears anywhere in the target file.
        # This is a naive substring match — it may match inside code blocks or comments.
        # For strict validation, heading parsing would be needed.
        target_text = target_path.read_text(encoding="utf-8")
        if anchor not in target_text:
            raise ValueError(
                f"Anchor={anchor} not found in file={target_relative} (linked from {file})!"
            )


def main(
    http_skips: Optional[List[str]] = None,
    url_skips: Optional[List[str]] = None,
    check_internal: bool = False,
) -> None:  # pylint: disable=too-many-locals
    """Check for broken or HTTP links"""
    all_md_files = [
        str(p.relative_to("."))
        for p in chain(
            Path("docs").rglob("*.md"),
            Path("packages").rglob("*.md"),
            Path(".").glob("*.md"),
        )
    ]

    broken_links: Dict[str, Dict] = {}
    http_links: Dict[str, List[str]] = {}

    # Configure request retries
    retry_strategy = Retry(
        total=3,  # number of retries
        status_forcelist=[404, 429, 500, 502, 503, 504],  # codes to retry on
    )
    # https://stackoverflow.com/questions/18466079/change-the-connection-pool-size-for-pythons-requests-module-when-in-threading
    adapter = HTTPAdapter(
        max_retries=retry_strategy, pool_connections=100, pool_maxsize=100
    )
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Run all file checks in a thread pool
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for md_file in all_md_files:
            print(f"Checking {str(md_file)}...")
            futures.append(
                executor.submit(check_file, session, md_file, http_skips, url_skips)
            )

        # Awaiting for results is blocking
        print("Awaiting for results...")
        future_results = [future.result() for future in futures]

        # Get errors
        for i in future_results:
            if i["http_links"]:
                http_links[i["file"]] = i["http_links"]
            if i["broken_links"]:
                broken_links[i["file"]] = i["broken_links"]

        # Check errors
        if broken_links:
            broken_links_str = "\n".join(
                [
                    f"{file_name}: {[entry['url'] + ', status: ' + str(entry['status_code']) for entry in error_data]}"
                    for file_name, error_data in broken_links.items()
                ]
            )
            print(f"Found broken url in the docs:\n{broken_links_str}")

        if http_links:
            http_links_str = "\n".join(
                [
                    f"{file_name}: {[url[1] for url in urls]}"
                    for file_name, urls in http_links.items()
                ]
            )
            print(
                f"Found HTTP urls in the docs:\n{http_links_str}\nTry to use HTTPS equivalent urls or add them to 'http_skips' if not possible"
            )

        # Internal link checks (opt-in)
        internal_errors: Dict[str, List[str]] = {}
        if check_internal and DOCS_DIR.exists():
            all_docs_files = set(DOCS_DIR.rglob("*.md"))
            for doc_file in sorted(all_docs_files):
                print(f"Checking internal links in {doc_file}...")
                errs = _check_internal_links(doc_file, all_docs_files)
                if errs:
                    internal_errors[str(doc_file)] = errs

        if internal_errors:
            internal_str = "\n".join(
                f"{fname}: {errs}"
                for fname, errs in internal_errors.items()
            )
            print(f"Found internal link errors:\n{internal_str}")

        if broken_links or http_links or internal_errors:
            sys.exit(1)

        print("OK")
        sys.exit(0)
