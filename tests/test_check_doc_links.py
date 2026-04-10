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

"""Tests for the check_doc_links module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from tomte.tools.check_doc_links import check_file


def _write_md(content: str) -> str:
    """Write content to a temp .md file and return its path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return f.name


def test_urls_in_fenced_code_blocks_are_skipped() -> None:
    """URLs inside fenced code blocks should not be checked."""
    content = """# Example

Some text.

``` python
response = requests.get('http://127.0.0.1:8000')
response = requests.get('http://127.0.0.1:8000/pets')
```

More text.
"""
    md_file = _write_md(content)
    session = MagicMock()
    result = check_file(session, md_file)
    assert result["broken_links"] == [], f"Expected no broken links, got {result['broken_links']}"
    assert result["http_links"] == [], f"Expected no HTTP links, got {result['http_links']}"
    session.head.assert_not_called()
    session.get.assert_not_called()
    Path(md_file).unlink()


def test_urls_in_fenced_block_with_backtick_inside() -> None:
    """Fenced code block containing a backtick should still be stripped."""
    content = '''# Example

``` python
x = "backtick: `"
url = "http://localhost:9999/api"
```

No URLs here.
'''
    md_file = _write_md(content)
    session = MagicMock()
    result = check_file(session, md_file)
    assert result["broken_links"] == []
    assert result["http_links"] == []
    session.head.assert_not_called()
    Path(md_file).unlink()


def test_urls_in_inline_code_are_skipped() -> None:
    """URLs inside inline code backticks should not be checked."""
    content = "Use `http://127.0.0.1:5000/api` for local testing.\n"
    md_file = _write_md(content)
    session = MagicMock()
    result = check_file(session, md_file)
    assert result["broken_links"] == []
    assert result["http_links"] == []
    session.head.assert_not_called()
    Path(md_file).unlink()


def test_urls_outside_code_blocks_are_checked() -> None:
    """URLs in normal text should still be checked."""
    content = "Visit https://example.com for details.\n"
    md_file = _write_md(content)
    session = MagicMock()
    session.head.return_value.status_code = 200
    result = check_file(session, md_file)
    assert result["broken_links"] == []
    session.head.assert_called_once()
    Path(md_file).unlink()


def test_invalid_url_caught_not_crashed() -> None:
    """Malformed URLs should be reported as broken, not crash the checker."""
    content = "See https://malformed-example.com/path' for details.\n"
    md_file = _write_md(content)
    session = MagicMock()
    from requests.exceptions import InvalidURL

    session.head.side_effect = InvalidURL("bad url")
    result = check_file(session, md_file)
    assert len(result["broken_links"]) == 1
    Path(md_file).unlink()
