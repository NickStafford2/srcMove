#!/usr/bin/env python3
"""Focused end-to-end checks for opt-in shadow correspondence diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(srcmove: Path, fixture: Path, output: Path, diagnostics: bool) -> dict:
    command = [
        str(srcmove),
        str(fixture),
        "--results-only",
        "--results",
        str(output),
    ]
    if diagnostics:
        command.append("--diagnostics")
    subprocess.run(command, check=True)
    return json.loads(output.read_text(encoding="utf-8"))


def has_record(
    records: list[dict], *, selection_status: str, classification: str, reason: str
) -> bool:
    return any(
        record["selection"]["status"] == selection_status
        and record["location"]["classification"] == classification
        and record["location"]["reason"] == reason
        for record in records
    )


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: check_shadow_diagnostics.py SRCMOVE FIXTURE")
    srcmove = Path(sys.argv[1])
    fixture = Path(sys.argv[2])
    with tempfile.TemporaryDirectory(prefix="srcmove-shadow-") as directory:
        root = Path(directory)
        ordinary = run(srcmove, fixture, root / "ordinary.json", False)
        diagnostic = run(srcmove, fixture, root / "diagnostic.json", True)

    assert "diagnostics" not in ordinary
    assert ordinary["results_schema_version"] == diagnostic["results_schema_version"] == 3
    diagnostic_without_evidence = dict(diagnostic)
    evidence = diagnostic_without_evidence.pop("diagnostics")
    assert ordinary == diagnostic_without_evidence
    assert evidence["schema_version"] == 5
    records = evidence["correspondences"]
    correspondence_ids = [
        (record["original_candidate_id"], record["modified_candidate_id"])
        for record in records
    ]
    assert correspondence_ids == sorted(correspondence_ids)
    assert has_record(
        records,
        selection_status="not_selected_pair",
        classification="restructured",
        reason="ancestor_wrapped",
    )
    assert has_record(
        records,
        selection_status="not_selected_pair",
        classification="stationary",
        reason="same_anchor_interval",
    )
    assert has_record(
        records,
        selection_status="selected_pair",
        classification="relocated",
        reason="crossed_stable_sibling",
    )
    print("PASS shadow diagnostics tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
