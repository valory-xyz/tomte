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
        # Gate on report file presence AND non-zero size — without these,
        # a gitleaks run that errored mid-write (permission denied, disk
        # full, partial flush) with a 0/1 exit produces a missing or
        # truncated report we'd then silently treat as "0 findings",
        # effectively disabling the baseline.
        report_file = Path(report_path)
        if not report_file.exists():
            sys.stderr.write(proc.stderr)
            raise SystemExit(
                f"gitleaks reported success ({proc.returncode}) but wrote no "
                f"report file at {report_path}; aborting."
            )
        if report_file.stat().st_size == 0:
            sys.stderr.write(proc.stderr)
            raise SystemExit(
                f"gitleaks reported success ({proc.returncode}) but the "
                f"report at {report_path} is empty (0 bytes). Likely a "
                f"truncated write or upstream crash; aborting rather than "
                f"freezing an empty baseline."
            )
        findings = json.loads(report_file.read_text(encoding="utf-8"))
        fingerprints: List[str] = sorted({_fingerprint(f) for f in findings})
        Path(output).write_text(
            "\n".join(fingerprints) + ("\n" if fingerprints else ""),
            encoding="utf-8",
        )
        sys.stderr.write(
            f"freeze-gitleaks: wrote {len(fingerprints)} fingerprint(s) to {output}\n"
        )
    finally:
        # The report path may have already vanished (e.g. tmp janitor
        # deleted it, or it was never created on a fast-path abort);
        # `missing_ok` keeps the cleanup tolerant.
        Path(report_path).unlink(missing_ok=True)


def _fingerprint(finding: dict) -> str:
    if "Fingerprint" in finding and finding["Fingerprint"]:
        return finding["Fingerprint"]
    return f"{finding.get('Commit', '')}:{finding['File']}:{finding['RuleID']}:{finding['StartLine']}"
