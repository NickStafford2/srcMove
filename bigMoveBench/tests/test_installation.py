from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from bigMoveBench import installation


class BigCloneBenchInstallationTests(unittest.TestCase):
    def test_preflight_reports_manual_prerequisites_without_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            installation.shutil, "which", return_value=None
        ):
            failures = installation.preflight(
                Path(temporary) / "missing-BigCloneEval"
            )

        self.assertTrue(any("database" in failure for failure in failures))
        self.assertTrue(any("H2 driver" in failure for failure in failures))
        self.assertTrue(any("IJaDataset" in failure for failure in failures))
        self.assertIn("Java executable not found on PATH", failures)

    def test_preflight_rejects_an_empty_ijadataset_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bce_dir = Path(temporary) / "BigCloneEval"
            (bce_dir / "bigclonebenchdb").mkdir(parents=True)
            (bce_dir / "bigclonebenchdb" / "bcb.h2.db").touch()
            (bce_dir / "libs").mkdir()
            (bce_dir / "libs" / "h2-1.3.176.jar").touch()
            (bce_dir / "ijadataset").mkdir()
            with mock.patch.object(
                installation.shutil, "which", return_value="/usr/bin/java"
            ):
                failures = installation.preflight(bce_dir)

        self.assertEqual(len(failures), 1)
        self.assertIn("IJaDataset Java corpus not found", failures[0])

    def test_preflight_accepts_reduced_ijadataset_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bce_dir = Path(temporary) / "BigCloneEval"
            (bce_dir / "bigclonebenchdb").mkdir(parents=True)
            (bce_dir / "bigclonebenchdb" / "bcb.h2.db").touch()
            (bce_dir / "libs").mkdir()
            (bce_dir / "libs" / "h2-1.3.176.jar").touch()
            source_dir = bce_dir / "ijadataset" / "bcb_reduced" / "2" / "default"
            source_dir.mkdir(parents=True)
            (source_dir / "131818.java").touch()
            with mock.patch.object(
                installation.shutil, "which", return_value="/usr/bin/java"
            ):
                failures = installation.preflight(bce_dir)

        self.assertEqual(failures, [])

    def test_successful_cli_lists_every_verified_prerequisite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bce_dir = Path(temporary) / "BigCloneEval"
            database = bce_dir / "bigclonebenchdb" / "bcb.h2.db"
            driver = bce_dir / "libs" / "h2-1.3.176.jar"
            source = bce_dir / "ijadataset" / "default" / "example.java"
            for path in (database, driver, source):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            output = io.StringIO()
            with mock.patch.object(
                installation.shutil, "which", return_value="/usr/bin/java"
            ), redirect_stdout(output):
                status = installation.main(bce_dir)

        self.assertEqual(status, 0)
        rendered = output.getvalue()
        self.assertIn("BigCloneBench preflight passed", rendered)
        self.assertIn(f"[ok] Database:   {database}", rendered)
        self.assertIn(f"[ok] H2 driver:  {driver}", rendered)
        self.assertIn(f"[ok] IJaDataset: {bce_dir / 'ijadataset'} (flat layout)", rendered)
        self.assertIn("[ok] Java:", rendered)


if __name__ == "__main__":
    unittest.main()
