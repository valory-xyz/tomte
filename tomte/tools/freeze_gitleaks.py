"""Run gitleaks against tomte canonical config; emit current findings to .gitleaksignore.

Developer-facing helper. Expected usage: run after `gitleaks detect` reports
false-positive findings against historical commits, to acknowledge them as
the new baseline.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

from tomte.configs import GITLEAKS_TOML


def main(output: str = ".gitleaksignore", gitleaks_executable: str = "gitleaks") -> None:
    if shutil.which(gitleaks_executable) is None:
        raise SystemExit(
            f"`{gitleaks_executable}` not found on PATH. Install gitleaks first "
            "(brew install gitleaks / wget the release binary)."
        )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as report:
        report_path = report.name
    try:
        # gitleaks exits 1 when leaks are found — that's the expected case here,
        # we're capturing them. Other non-zero exits (binary missing, config
        # invalid, etc.) we want to surface.
        proc = subprocess.run(
            [
                gitleaks_executable,
                "detect",
                "--config",
                str(GITLEAKS_TOML),
                "-f",
                "json",
                "-r",
                report_path,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode not in (0, 1):
            sys.stderr.write(proc.stderr)
            raise SystemExit(
                f"gitleaks failed with exit code {proc.returncode}; aborting."
            )
        # Gate on report file presence — without this, a gitleaks run that
        # errored mid-write (permission denied, disk full) with a 0/1 exit
        # produces a missing or truncated report we'd then silently treat
        # as "0 findings", effectively disabling the baseline.
        if not Path(report_path).exists():
            sys.stderr.write(proc.stderr)
            raise SystemExit(
                f"gitleaks reported success ({proc.returncode}) but wrote no "
                f"report file at {report_path}; aborting."
            )
        findings = json.loads(Path(report_path).read_text(encoding="utf-8") or "[]")
        fingerprints: List[str] = sorted({_fingerprint(f) for f in findings})
        Path(output).write_text(
            "\n".join(fingerprints) + ("\n" if fingerprints else ""),
            encoding="utf-8",
        )
        sys.stderr.write(
            f"freeze-gitleaks: wrote {len(fingerprints)} fingerprint(s) to {output}\n"
        )
    finally:
        os.unlink(report_path)


def _fingerprint(finding: dict) -> str:
    if "Fingerprint" in finding and finding["Fingerprint"]:
        return finding["Fingerprint"]
    return f"{finding.get('Commit', '')}:{finding['File']}:{finding['RuleID']}:{finding['StartLine']}"
