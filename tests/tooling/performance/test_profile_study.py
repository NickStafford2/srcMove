from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from performance.profile_study import _load_records, _report, _result_medians


EXAMPLES = Path(__file__).resolve().parents[3] / "doc/plans/results_schema_v3/examples"


def capture(root: Path, payloads: list[tuple[str | None, str, str]]) -> dict:
    rows = []
    for index, (payload, phase, status) in enumerate(payloads):
        attempt = root / "attempts" / str(index)
        attempt.mkdir(parents=True)
        (attempt / "attempt.json").write_text('{"xml": {"size_bytes": 123}}', encoding="utf-8")
        if payload is not None:
            (attempt / "results.json").write_text(payload, encoding="utf-8")
        rows.append(dict(variant="current", workload="tiny", phase=phase, status=status,
                         attempt_path=f"attempts/{index}", wall_seconds="0.25"))
    with (root / "raw.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {"observation": {"executables": {"current": {
        "artifact": {"sha256": "a" * 64}, "receipt": {"sources": {"srcMove": {"commit": "fixture"}}},
    }}}}


class ProfileStudyTests(unittest.TestCase):
    def test_schema3_counts_reach_raw_records_medians_and_report(self) -> None:
        for example, expected in [("empty", (0, 0, 0, 0)), ("selected-pair", (2, 2, 1, 1)),
                                  ("ordered-sequence", (6, 6, 3, 3))]:
            with self.subTest(example=example), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                payload = (EXAMPLES / f"{example}.json").read_text(encoding="utf-8")
                manifest = capture(root, [(payload, "measured", "success")])
                records = _load_records(root, manifest)
                counts = _result_medians(records)["tiny"]
                for key, value in zip(("regions_total", "candidates_total", "groups_total", "move_group_count"), expected):
                    self.assertEqual(records[0][key], value)
                    self.assertEqual(counts[key], value)
                self.assertEqual(counts["content_relationships"], {"type1": expected[3], "type2c": 0, "type3": 0})
                self.assertEqual(records[0]["results_record_status"], "valid")
                self.assertEqual(records[0]["wall_seconds"], 0.25)
                self.assertEqual(records[0]["source_commit"], "fixture")
                summary = {"variants": {"current": {"workloads": {"tiny": {"metrics": {}}}}}}
                self.assertIn(f"atomic move groups={expected[3]}", _report(summary, {"tiny": counts}))

    def test_unavailable_or_invalid_results_keep_timings_without_inventing_counts(self) -> None:
        selected = json.loads((EXAMPLES / "selected-pair.json").read_text(encoding="utf-8"))
        selected["summary"]["atomic_move_group_count"] = 99
        cases = [(None, "missing"), ("{", "malformed"), ("[]", "malformed"),
                 (json.dumps(selected), "invalid_schema"),
                 ('{"results_schema_version": 2, "move_count": 1}', "invalid_schema")]
        for payload, expected_status in cases:
            with self.subTest(status=expected_status, payload=payload), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest = capture(root, [(payload, "measured", "success")])
                records = _load_records(root, manifest)
                self.assertEqual(records[0]["results_record_status"], expected_status)
                self.assertEqual(records[0]["wall_seconds"], 0.25)
                counts = _result_medians(records)["tiny"]
                for key in ("regions_total", "candidates_total", "groups_total", "move_group_count"):
                    self.assertIsNone(counts[key])
                self.assertEqual(counts["content_relationships"], {})
                self.assertEqual(counts["output_size_bytes"], 123)

    def test_only_valid_successful_measured_results_supply_content_counts(self) -> None:
        selected = (EXAMPLES / "selected-pair.json").read_text(encoding="utf-8")
        sequence = (EXAMPLES / "ordered-sequence.json").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = capture(root, [(sequence, "warmup", "success"), (sequence, "measured", "failed"),
                                      (None, "measured", "success"), (selected, "measured", "success")])
            counts = _result_medians(_load_records(root, manifest))["tiny"]
            self.assertEqual(counts["move_group_count"], 1)
            self.assertEqual(counts["content_relationships"], {"type1": 1, "type2c": 0, "type3": 0})
