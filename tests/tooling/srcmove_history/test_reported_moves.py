"""Compound reports survive compact history without becoming NxM groups."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from srcmove_history.compact import compact_pair_outcome
from srcmove_history.contracts import PairOutcome, PairStatus, VerifiedArtifact
from srcmove_history.database import AnalysisDatabase
from srcmove_history.inputs import build_pair_work_items, observe_executable
from srcmove_history.queries import AnalysisReader
from srcmove_history.report import build_report
from srcmove_history.results import normalize_compactable_results
from tests.tooling.srcmove_history import test_srcmove_history_database as fixture
from srcmove_history.retention import RetentionPolicy


def results() -> dict:
    moves = [
        {"move_id": name, "content_relationship": "type1",
         "from_xpaths": [f'/src:unit[@filename="old.cpp"]/{name}'], "to_xpaths": [f'/src:unit[@filename="new.cpp"]/{name}'],
         "from_raw_texts": [f"{name}();"], "to_raw_texts": [f"{name}();"]}
        for name in ("a", "b", "c")
    ]
    sequence = {"move_id": "sequence:a", "report_kind": "ordered_sequence",
                "content_relationship": "type1", "member_move_ids": ["a", "b"]}
    for field in ("from_xpaths", "to_xpaths", "from_raw_texts", "to_raw_texts"):
        sequence[field] = [item for move in moves[:2] for item in move[field]]
    return {
        "results_schema_version": 2, "move_count": 3, "move_group_count": 3,
        "move_pair_count": 3, "annotated_region_count": 6,
        "group_kinds": {"one_to_one": 3}, "content_relationships": {"type1": 3},
        "moves": moves,
        "reported_moves": [sequence, {**moves[2], "report_kind": "atomic", "member_move_ids": ["c"]}],
        "reported_move_count": 2, "reported_content_relationships": {"type1": 2},
        "move_sequences": [{"sequence_id": "sequence:a", "content_relationship": "type1", "policy": "ordered_adjacent_v1", "member_move_ids": ["a", "b"],
                            **{side: {"revision_file": side + ".cpp", "parent_id": "/parent", "first_child_ordinal": 1, "last_child_ordinal": 2, "member_xpaths": sequence[side + "_xpaths"]} for side in ("from", "to")}}],
        "sequence_cluster_count": 1, "sequence_reporting_unit_count": 2,
    }


def outcome(path: Path, work, value: dict) -> PairOutcome:
    content = json.dumps(value).encode()
    path.write_bytes(content)
    return PairOutcome(
        work, PairStatus.COMPLETED,
        artifacts=(VerifiedArtifact(path, len(content), hashlib.sha256(content).hexdigest(), "json_results", "valid", "srcmove"),),
        metrics=tuple((name, count) for name, count in value.items() if isinstance(count, int)),
    )


class ReportedMovesTests(unittest.TestCase):
    def test_reports_partition_atomic_matches_and_reject_cross_links(self):
        normalize_compactable_results(results())
        for mutation in ("repeat", "omit", "crosslink", "type", "count", "invalid_id"):
            value = results()
            report = value["reported_moves"][0]
            if mutation == "repeat":
                report["member_move_ids"] = ["a", "a"]
            elif mutation == "omit":
                value["reported_moves"].pop()
                value["reported_move_count"] = 1
            elif mutation == "crosslink":
                report["to_xpaths"].reverse()
            elif mutation == "type":
                report["content_relationship"] = "type3"
            elif mutation == "invalid_id":
                value["moves"][0]["move_id"] = []
            else:
                value["reported_content_relationships"] = {"type1": 3}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                normalize_compactable_results(value)

    def test_contradictory_sequence_metadata_is_rejected(self):
        for mutation in ("count", "order", "member", "ordinal"):
            value = results()
            sequence = value["move_sequences"][0]
            if mutation == "count":
                value["sequence_reporting_unit_count"] = 3
            elif mutation == "order":
                sequence["to"]["member_xpaths"].reverse()
            elif mutation == "member":
                sequence["member_move_ids"] = ["a", "c"]
            else:
                sequence["from"]["last_child_ordinal"] = 3
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                normalize_compactable_results(value)

    def test_sequence_compaction_discards_unknown_source_payload(self):
        value = results()
        value["move_sequences"][0]["from_raw_texts"] = ["secret source payload"]
        value["move_sequences"][0]["from"]["source_text"] = "other secret payload"
        from srcmove_history.contracts import PairWorkItem
        with tempfile.TemporaryDirectory() as temporary:
            compact = compact_pair_outcome(outcome(Path(temporary) / "results.json", PairWorkItem(0, "old", "new", "fingerprint"), value))
            self.assertNotIn(b"secret", compact.metrics_json)

    def test_reports_survive_database_queries_and_keep_raw_text_ephemeral(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            manifest = fixture.AnalysisDatabaseTests()._manifest(
                repository, observe_executable(fixture.executable(root / "srcdiff")),
                observe_executable(fixture.executable(root / "srcmove")), commits=("new", "old"),
            )
            analysis = root / "analysis"
            with AnalysisDatabase.create(analysis, manifest, batch_id="a" * 32,
                                         target_kind="total_pairs", target_value="1", reaches_root=True, retention_policy=RetentionPolicy()) as database:
                batch = database.pending_batch()
                invocation = fixture.begin_invocation(database)
                pair = outcome(root / "results.json", build_pair_work_items(manifest)[0], results())
                compact = compact_pair_outcome(pair)
                self.assertNotIn(b"a();", compact.metrics_json)
                database.record_outcome(batch, pair, invocation_id=invocation)
                database.commit_pending_batch(batch)
                summary = database.summary()
                self.assertEqual(summary["move_group_count"], 3)
                self.assertEqual(summary["reported_move_count"], 2)
                self.assertEqual(summary["reported_content_relationships"], {"type1": 2})
                detail = database.pair_details(0)
                self.assertEqual(len(detail["moves"]), 3)
                self.assertEqual(len(detail["reported_moves"]), 2)
                self.assertEqual(detail["move_sequences"], results()["move_sequences"])
            reader = AnalysisReader(analysis)
            status = reader.status().record()
            self.assertEqual(status["reported_move_count"], 2)
            self.assertEqual(status["move_group_count"], 3)
            detail = reader.show(1).record()
            self.assertEqual(detail["reported_moves"][0]["member_move_ids"], ["a", "b"])
            self.assertEqual([row["move_id"] for row in detail["atomic_metadata"]], ["a", "b", "c"])
            self.assertEqual(reader.list_pairs().items[0].reported_move_count, 2)
            with patch("srcmove_history.report._positive_git_count", return_value=2), patch("srcmove_history.report._commit_date", return_value="2026-10-05"), patch("srcmove_history.report._repository_name", return_value="fixture"):
                report = build_report(analysis)
            self.assertEqual(report.move_groups, 2)
            self.assertEqual(report.atomic_move_groups, 3)
            self.assertEqual(report.cross_file_moves, 2)
            self.assertEqual(dict(report.content_relationships), {"type1": 2})

    def test_atomic_metadata_links_primary_members_without_guessing_absent_fields(self):
        from srcmove_history.contracts import PairWorkItem
        value = results()
        value["moves"][0].update(identity_status="unresolved", identity_reason="repeated source", selection_reason="selected")
        value["reported_moves"][0].update(identity_status="unresolved", identity_reason="member ambiguity")
        with tempfile.TemporaryDirectory() as temporary:
            work = PairWorkItem(0, "old", "new", "fingerprint")
            first = compact_pair_outcome(outcome(Path(temporary) / "results.json", work, value))
            second = compact_pair_outcome(outcome(Path(temporary) / "results.json", work, value))
            self.assertEqual(first.metrics_json, second.metrics_json)
            metrics = json.loads(first.metrics_json)
            metadata = metrics["atomic_metadata"]
            self.assertEqual(metadata[0], {"ordinal": 0, "move_id": "a", "identity_status": "unresolved", "identity_reason": "repeated source", "selection_reason": "selected"})
            by_id = {row["move_id"]: row for row in metadata}
            self.assertEqual([by_id[name]["ordinal"] for name in metrics["reported_moves"][0]["member_move_ids"]], [0, 1])
            self.assertNotIn("identity_status", metadata[1])
            self.assertEqual(metrics["reported_moves"][0]["identity_reason"], "member ambiguity")

    def test_pair_detail_exposes_metadata_sidecar_and_old_absence(self):
        from srcmove_history.queries import PairDetailSnapshot
        common = dict(number=1, distance_from_newest=0, old_commit="old", new_commit="new", pair_fingerprint="fingerprint", status="completed", invocation_id="id", changed_path_count=1, analyzable_path_count=1, timings=(), error=None, failure_evidence=None, results_observation=None, moves=())
        from srcmove_history.queries import _freeze_json
        old = PairDetailSnapshot(metrics=_freeze_json({"move_count": 1}), **common).record()
        self.assertNotIn("atomic_metadata", old)
        sidecar = [{"ordinal": 0, "move_id": "a"}]
        current = PairDetailSnapshot(metrics=_freeze_json({"atomic_metadata": sidecar}), **common).record()
        self.assertEqual(current["atomic_metadata"], sidecar)

    def test_legacy_results_do_not_invent_sequences(self):
        value = results()
        for field in list(value):
            if field.startswith("reported_") or field.startswith("sequence_") or field == "move_sequences":
                del value[field]
        for move in value["moves"]:
            del move["move_id"]
        normalize_compactable_results(value)
        with tempfile.TemporaryDirectory() as temporary:
            from srcmove_history.contracts import PairWorkItem
            compact = compact_pair_outcome(outcome(Path(temporary) / "results.json", PairWorkItem(0, "old", "new", "fingerprint"), value))
            metrics = json.loads(compact.metrics_json)
            self.assertNotIn("reported_moves", metrics)
            self.assertNotIn("move_sequences", metrics)
            self.assertEqual(metrics["atomic_metadata"], [{"ordinal": 0}, {"ordinal": 1}, {"ordinal": 2}])


if __name__ == "__main__":
    unittest.main()
