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


def has_record(records: list[dict], **expected: str) -> bool:
    return any(all(record.get(key) == value for key, value in expected.items())
               for record in records)


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
    diagnostic_without_evidence = dict(diagnostic)
    evidence = diagnostic_without_evidence.pop("diagnostics")
    assert ordinary == diagnostic_without_evidence
    assert evidence["schema_version"] == 3
    records = evidence["correspondences"]
    correspondence_ids = [
        (record["delete_candidate_id"], record["insert_candidate_id"])
        for record in records
    ]
    assert correspondence_ids == sorted(correspondence_ids)
    assert has_record(
        records,
        current_result="not_move",
        shadow_change="restructured",
        classification_reason="ancestor_wrapped",
    )
    assert has_record(
        records,
        current_result="not_move",
        shadow_change="stationary",
        classification_reason="same_anchor_interval",
    )
    assert has_record(
        records,
        current_result="move",
        shadow_change="relocated",
        classification_reason="crossed_stable_sibling",
    )
    print("PASS shadow diagnostics tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
