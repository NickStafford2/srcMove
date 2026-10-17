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
from srcmove_history.results import normalize_compactable_results, scalar_metrics
from tests.tooling.srcmove_history import test_srcmove_history_database as fixture
from srcmove_history.retention import RetentionPolicy


def results() -> dict:
    from tests.tooling.results_fixtures import schema3_fixture
    value = schema3_fixture({'moves': [
        {'move_id': name, 'from_raw_texts': [name + '();'],
         'to_raw_texts': [name + '();'],
         'from_xpaths': [f'/src:unit[@filename="old.cpp"][1]/src:expr_stmt[{i}]'],
         'to_xpaths': [f'/src:unit[@filename="new.cpp"][1]/src:expr_stmt[{i}]']}
        for i, name in enumerate(('a', 'b', 'c'), 1)]})
    for group in value['atomic_move_groups']:
        group['original'][0]['revision_file'] = 'old.cpp'
        group['modified'][0]['revision_file'] = 'new.cpp'
    value['output_items'] = [
        {'id': 'sequence:a', 'kind': 'sequence_move_group', 'member_group_ids': ['a', 'b'],
         'sequence': {'policy': 'ordered_adjacent_v1', **{
             side: {'revision_file': filename, 'parent_id': '/parent',
                    'first_child_ordinal': 1, 'last_child_ordinal': 2}
             for side, filename in [('original', 'old.cpp'), ('modified', 'new.cpp')]}}},
        {'id': 'item:c', 'kind': 'atomic_move_group', 'member_group_ids': ['c']}]
    value['summary'].update(output_item_count=2, sequence_move_group_count=1,
                            output_content_relationships={'type1': 2, 'type2c': 0, 'type3': 0})
    return value


def outcome(path: Path, work, value: dict) -> PairOutcome:
    content = json.dumps(value).encode()
    path.write_bytes(content)
    return PairOutcome(
        work, PairStatus.COMPLETED,
        artifacts=(VerifiedArtifact(path, len(content), hashlib.sha256(content).hexdigest(), "json_results", "valid", "srcmove"),),
        metrics=tuple(scalar_metrics(value).items()),
    )


class ReportedMovesTests(unittest.TestCase):
    def test_reports_partition_atomic_matches_and_reject_cross_links(self):
        normalize_compactable_results(results())
        mutations = [
            lambda p: p['output_items'][0].update(member_group_ids=['a', 'a']),
            lambda p: p['output_items'].pop(),
            lambda p: p['output_items'][0].update(id='sequence:b'),
            lambda p: p['atomic_move_groups'][0].update(content_relationship='type3'),
            lambda p: p['summary'].update(output_item_count=3),
            lambda p: p['atomic_move_groups'][0].update(id=[]),
        ]
        for mutation in mutations:
            value = results()
            mutation(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_compactable_results(value)

    def test_contradictory_sequence_metadata_is_rejected(self):
        for mutation in ('count', 'file', 'member', 'ordinal'):
            value = results()
            sequence = value['output_items'][0]
            if mutation == 'count':
                value['summary']['sequence_move_group_count'] = 0
            elif mutation == 'file':
                sequence['sequence']['modified']['revision_file'] = 'other.cpp'
            elif mutation == 'member':
                sequence['member_group_ids'] = ['a', 'missing']
            else:
                sequence['sequence']['original']['last_child_ordinal'] = 3
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                normalize_compactable_results(value)

    def test_sequence_compaction_rejects_unknown_source_payload(self):
        value = results()
        value['output_items'][0]['sequence']['original']['source_text'] = 'secret payload'
        with self.assertRaises(ValueError):
            normalize_compactable_results(value)

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
                self.assertEqual(summary["reported_content_relationships"].get("type1"), 2)
                detail = database.pair_details(0)
                self.assertEqual(len(detail["moves"]), 3)
                self.assertEqual(len(detail["reported_moves"]), 2)
                self.assertEqual(detail["output_items"], results()["output_items"])
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

    def test_atomic_evidence_survives_without_becoming_sequence_confidence(self):
        from srcmove_history.contracts import PairWorkItem
        value = results()
        value['atomic_move_groups'][0]['selection']['matching_weight_milli'] = 725
        with tempfile.TemporaryDirectory() as temporary:
            work = PairWorkItem(0, 'old', 'new', 'fingerprint')
            path = Path(temporary) / 'results.json'
            first = compact_pair_outcome(outcome(path, work, value))
            second = compact_pair_outcome(outcome(path, work, value))
            self.assertEqual(first.metrics_json, second.metrics_json)
            metrics = json.loads(first.metrics_json)
            retained = metrics['atomic_move_groups'][0]
            self.assertEqual(retained['selection'], value['atomic_move_groups'][0]['selection'])
            self.assertEqual(retained['correspondence'], {'status': 'selected_pair'})
            self.assertEqual(retained['original'][0]['candidate_id'], 0)
            self.assertNotIn('raw_text', retained['original'][0])
            self.assertIn('text_digest', retained['original'][0])
            self.assertEqual(metrics['output_items'], value['output_items'])
            self.assertNotIn('selection', metrics['reported_moves'][0])
            self.assertNotIn('selection', metrics['output_items'][0])

    def test_pair_detail_exposes_metadata_sidecar_and_old_absence(self):
        from srcmove_history.queries import PairDetailSnapshot
        common = dict(number=1, distance_from_newest=0, old_commit="old", new_commit="new", pair_fingerprint="fingerprint", status="completed", invocation_id="id", changed_path_count=1, analyzable_path_count=1, timings=(), error=None, failure_evidence=None, results_observation=None, moves=())
        from srcmove_history.queries import _freeze_json
        old = PairDetailSnapshot(metrics=_freeze_json({"move_count": 1}), **common).record()
        self.assertNotIn("atomic_metadata", old)
        sidecar = [{"ordinal": 0, "move_id": "a"}]
        current = PairDetailSnapshot(metrics=_freeze_json({"atomic_metadata": sidecar}), **common).record()
        self.assertEqual(current["atomic_metadata"], sidecar)

    def test_legacy_results_are_rejected_at_live_admission(self):
        value = {'results_schema_version': 2, 'moves': [], 'move_count': 0}
        with self.assertRaises(ValueError):
            normalize_compactable_results(value)


if __name__ == "__main__":
    unittest.main()
