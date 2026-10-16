"""Read-only compact-3 compatibility preserves strict execution contracts."""
from pathlib import Path
import dataclasses
import json
import sys
import tempfile
import unittest

from srcmove_history.database import AnalysisDatabase
from srcmove_history.inputs import FingerprintSchemaVersions, canonical_pretty_json_bytes, load_frozen_manifest_bytes, observe_executable, verify_resume_inputs
from srcmove_history.queries import AnalysisReader
from srcmove_history.retention import RetentionPolicy
from tests.tooling.srcmove_history import test_srcmove_history_database as fixture


class ReadOnlyCompatibilityTests(unittest.TestCase):
    def make_manifest(self, root):
        repository = root / 'repository'
        repository.mkdir()
        return fixture.AnalysisDatabaseTests()._manifest(repository,
            observe_executable(fixture.executable(root / 'srcdiff')),
            observe_executable(fixture.executable(root / 'srcmove')), commits=('new', 'old'))

    def test_only_compact_three_is_allowed_and_only_by_read_opt_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.make_manifest(root)
            value = manifest.record()
            value['fingerprint_schema_versions']['compact_pair'] = 3
            content = canonical_pretty_json_bytes(value)
            with self.assertRaises(ValueError):
                load_frozen_manifest_bytes(content, analysis_root=root)
            old = load_frozen_manifest_bytes(content, analysis_root=root, allow_legacy_compact=True)
            self.assertEqual(old.schema_versions.compact_pair, 3)
            for version in (1, 2, 5, True):
                value['fingerprint_schema_versions']['compact_pair'] = version
                with self.subTest(version=version), self.assertRaises(ValueError):
                    load_frozen_manifest_bytes(canonical_pretty_json_bytes(value), analysis_root=root, allow_legacy_compact=True)
            value['fingerprint_schema_versions']['compact_pair'] = 3
            value['fingerprint_schema_versions']['srcmove_results_validator'] = 2
            with self.assertRaises(ValueError):
                load_frozen_manifest_bytes(canonical_pretty_json_bytes(value), analysis_root=root, allow_legacy_compact=True)

    def test_legacy_resume_and_compare_binding_remain_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = self.make_manifest(Path(temporary))
            old = dataclasses.replace(manifest, schema_versions=dataclasses.replace(manifest.schema_versions, compact_pair=3))
            kwargs = dict(repository_identity=manifest.repository_identity, configuration=manifest.configuration,
                          srcdiff=manifest.srcdiff, srcmove=manifest.srcmove)
            with self.assertRaisesRegex(ValueError, 'read-only'):
                verify_resume_inputs(old, **kwargs)
            self.assertEqual(verify_resume_inputs(manifest, **kwargs).schema_versions, FingerprintSchemaVersions())

    def test_database_read_only_flag_controls_manifest_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.make_manifest(root)
            old = dataclasses.replace(manifest, schema_versions=dataclasses.replace(manifest.schema_versions, compact_pair=3))
            state = root / 'state'
            with AnalysisDatabase.create(state, old, batch_id='a' * 32, target_kind='total_pairs', target_value='1', reaches_root=True, retention_policy=RetentionPolicy()):
                pass
            with AnalysisDatabase.open(state, read_only=True) as database:
                self.assertEqual(database.initial_manifest().schema_versions.compact_pair, 3)
            with AnalysisDatabase.open(state) as database:
                with self.assertRaises(ValueError):
                    database.initial_manifest()

    def test_old_pair_detail_keeps_absent_metadata_unknown(self):
        from srcmove_history.contracts import PairOutcome, PairStatus
        from srcmove_history.inputs import build_pair_work_items
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self.make_manifest(root)
            old = dataclasses.replace(manifest, schema_versions=dataclasses.replace(manifest.schema_versions, compact_pair=3))
            state = root / "state"
            with AnalysisDatabase.create(state, old, batch_id="a" * 32, target_kind="total_pairs", target_value="1", reaches_root=True, retention_policy=RetentionPolicy()) as database:
                batch = database.pending_batch()
                invocation = fixture.begin_invocation(database)
                database.record_outcome(batch, PairOutcome(build_pair_work_items(old)[0], PairStatus.NO_ANALYZABLE_CHANGE), invocation_id=invocation)
            detail = AnalysisReader(state).show(1).record()
            self.assertNotIn("atomic_metadata", detail)
            self.assertNotIn("atomic_metadata", detail["metrics"])


if __name__ == '__main__':
    unittest.main()
