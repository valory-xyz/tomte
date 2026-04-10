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

"""This CLI tool freezes the dependencies."""
import re
import subprocess  # nosec
from pathlib import Path
from typing import Optional, Tuple


def main(
    output_path: Optional[str] = None,
    exclude_packages: Optional[Tuple[str, ...]] = None,
) -> None:
    """Freeze pip dependencies to requirements format.

    :param output_path: path to write requirements to. If None, prints to stdout.
    :param exclude_packages: package names to exclude from output. Handles both
        dash and underscore variants (e.g. ``open-autonomy`` matches ``open_autonomy``).
    """
    pip_freeze_call = subprocess.Popen(  # nosec  # pylint: disable=consider-using-with
        ["pip", "freeze"], stdout=subprocess.PIPE
    )
    (stdout, _) = pip_freeze_call.communicate()
    requirements = stdout.decode("utf-8")

    if exclude_packages:
        for pkg in exclude_packages:
            # Normalize dashes/underscores so that --exclude-package open-autonomy
            # also matches open_autonomy==... in pip freeze output (and vice versa).
            # Split on separators first, escape each part, then rejoin with [-_].
            parts = re.split(r"[-_]", pkg)
            normalized = "[-_]".join(re.escape(p) for p in parts)
            requirements = re.sub(
                rf"^{normalized}(==.*| .*)?\n",
                "",
                requirements,
                flags=re.MULTILINE | re.IGNORECASE,
            )

    if output_path is None:
        print(requirements)
    else:
        path = Path(output_path)
        path.write_text(requirements, encoding="utf-8")
