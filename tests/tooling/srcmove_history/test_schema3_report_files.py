"""History reports use revision files, independently of locator spellings."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from srcmove_history.database import AnalysisDatabase
from srcmove_history.inputs import build_pair_work_items, observe_executable
from srcmove_history.report import build_report
from srcmove_history.retention import RetentionPolicy
from tests.tooling.srcmove_history import test_srcmove_history_database as database_fixture
from tests.tooling.srcmove_history.test_reported_moves import outcome, results


class Schema3ReportFilesTests(unittest.TestCase):
    def test_explicit_revision_files_override_locator_literals_and_null_stays_unknown(self):
        value = results()
        quoted = 'same\'"file.cpp'
        # Locator text deliberately names old.cpp/new.cpp. Reporting must use
        # revision_file, including quote characters without parsing the locator.
        for group in value['atomic_move_groups'][:2]:
            for side in ('original', 'modified'):
                group[side][0]['revision_file'] = quoted
        for side in ('original', 'modified'):
            value['output_items'][0]['sequence'][side]['revision_file'] = quoted
        value['atomic_move_groups'][2]['original'][0]['revision_file'] = None
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / 'repository'
            repository.mkdir()
            manifest = database_fixture.AnalysisDatabaseTests()._manifest(
                repository, observe_executable(database_fixture.executable(root / 'srcdiff')),
                observe_executable(database_fixture.executable(root / 'srcmove')), commits=('new', 'old'))
            analysis = root / 'analysis'
            with AnalysisDatabase.create(analysis, manifest, batch_id='a' * 32,
                                         target_kind='total_pairs', target_value='1', reaches_root=True,
                                         retention_policy=RetentionPolicy()) as database:
                batch = database.pending_batch()
                invocation = database_fixture.begin_invocation(database)
                database.record_outcome(batch, outcome(root / 'results.json', build_pair_work_items(manifest)[0], value),
                                        invocation_id=invocation)
                database.commit_pending_batch(batch)
            with patch('srcmove_history.report._positive_git_count', return_value=2), \
                 patch('srcmove_history.report._commit_date', return_value='2026-10-05'), \
                 patch('srcmove_history.report._repository_name', return_value='fixture'):
                report = build_report(analysis)
            self.assertEqual(report.within_file_moves, 1)
            self.assertEqual(report.cross_file_moves, 0)
            self.assertEqual(report.unclassified_location_moves, 1)
            self.assertEqual(report.move_groups, 2)
            self.assertEqual(report.atomic_move_groups, 3)
