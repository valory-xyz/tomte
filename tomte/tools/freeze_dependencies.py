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
import subprocess  # nosec
from pathlib import Path
from typing import Optional


def main(output_path: Optional[str]) -> None:
    pip_freeze_call = subprocess.Popen(  # nosec  # pylint: disable=consider-using-with
        ["pip", "freeze"], stdout=subprocess.PIPE
    )
    (stdout, stderr) = pip_freeze_call.communicate()
    requirements = stdout.decode("utf-8")

    if output_path is None:
        print(requirements)
    else:
        path = Path(output_path)
        path.write_text(requirements)
