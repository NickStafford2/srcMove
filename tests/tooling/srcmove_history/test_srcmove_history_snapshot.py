from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import shutil
import unittest
import zipfile

from tests.tooling.srcmove_history import test_srcmove_history_analysis as analysis_fixture
from srcmove_history.analysis import AnalysisTarget, analyze_repository
from srcmove_history.configuration import HistoryConfiguration, create_history_configuration
from srcmove_history.inputs import AnalysisConfiguration
from srcmove_history.locking import AnalysisBusyError, AnalysisOperationLock
from srcmove_history.snapshot import export_snapshot


class SnapshotTests(unittest.TestCase):
    def test_snapshot_is_immutable_and_extension_does_not_change_prior_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            helper = analysis_fixture.AnalyzeRepositoryTests()
            repository, _ = helper._history(root, 5)
            state = repository / ".srcmove"
            helper._analyze(state, repository, analysis_fixture.executable(root / "srcdiff"), analysis_fixture.executable(root / "srcmove"), total_pairs=2)
            create_history_configuration(state, HistoryConfiguration(AnalysisConfiguration(excluded_suffixes=(".txt",))))
            first = export_snapshot(state)
            content = Path(first["path"]).read_bytes()
            self.assertEqual(first, export_snapshot(state))
            with zipfile.ZipFile(first["path"]) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["covered_commit_pairs"], 2)
                for name, checksum in manifest["files"].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), checksum)
            analyze_repository(analysis_root=state, target=AnalysisTarget("additional_pairs", 1), jobs=1)
            second = export_snapshot(state)
            self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
            self.assertEqual(Path(first["path"]).read_bytes(), content)
            relocated = root / "different-mount" / repository.name
            relocated.parent.mkdir()
            shutil.move(str(repository), relocated)
            state = relocated / ".srcmove"
            relocated_snapshot = export_snapshot(state)
            self.assertEqual(second["snapshot_id"], relocated_snapshot["snapshot_id"])
            with zipfile.ZipFile(relocated_snapshot["path"]) as archive:
                self.assertEqual(json.loads(archive.read("status.json"))["analysis"]["root"], ".")
            with AnalysisOperationLock(state, command="test"):
                with self.assertRaises(AnalysisBusyError):
                    export_snapshot(state)
