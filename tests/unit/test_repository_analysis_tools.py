from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repository_analysis.inputs import observe_executable
from repository_analysis.tools import admit_executable


class AnalysisExecutableAdmissionTests(unittest.TestCase):
    def test_admission_rejects_a_regular_non_executable_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            analysis.mkdir()
            source = root / "srcdiff"
            source.write_bytes(b"#!/bin/sh\nexit 0\n")
            source.chmod(0o644)

            with self.assertRaisesRegex(
                ValueError, r"^executable is not executable:"
            ):
                admit_executable(source, analysis, role="srcdiff")

            self.assertEqual(list((analysis / "tools").rglob("*")), [])

    def test_admission_binds_identity_to_analysis_owned_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            analysis.mkdir()
            source = root / "srcdiff"
            source.write_bytes(b"#!/bin/sh\nexit 0\n")
            source.chmod(0o755)

            admitted = admit_executable(source, analysis, role="srcdiff")
            source.write_bytes(b"#!/bin/sh\nexit 99\n")

            current = observe_executable(admitted.requested_path)
            self.assertNotEqual(current.sha256, observe_executable(source).sha256)
            self.assertEqual(current.sha256, admitted.sha256)
            self.assertTrue(admitted.resolved_path.is_relative_to(analysis.resolve()))
            self.assertFalse(admitted.resolved_path.stat().st_mode & 0o222)

    def test_repeated_admission_reuses_identical_role_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            analysis = root / "analysis"
            analysis.mkdir()
            source = root / "srcmove"
            source.write_bytes(b"#!/bin/sh\nexit 0\n")
            source.chmod(0o755)

            first = admit_executable(source, analysis, role="srcmove")
            second = admit_executable(source, analysis, role="srcmove")

            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
