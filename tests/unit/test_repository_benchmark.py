from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_TOOL = REPO_ROOT / "tests" / "fixtures" / "benchmark" / "fake_tool.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.repositories.run_case import run_staged_repository_benchmark


def executable_copy(root: Path, name: str) -> Path:
    destination = root / name
    shutil.copy2(FAKE_TOOL, destination)
    destination.chmod(0o755)
    return destination


def source_pair(root: Path) -> tuple[Path, Path]:
    original = root / "exports" / "original"
    modified = root / "exports" / "modified"
    original.mkdir(parents=True, exist_ok=True)
    modified.mkdir(parents=True, exist_ok=True)
    (original / "sample.cpp").write_text("int before;\n", encoding="utf-8")
    (modified / "sample.cpp").write_text("int after;\n", encoding="utf-8")
    return original, modified


class RepositoryBenchmarkTests(unittest.TestCase):
    def run_benchmark(
        self, root: Path, *, srcdiff_name: str = "srcdiff-valid-archive"
    ):
        original, modified = source_pair(root)
        tools = root / "tools"
        tools.mkdir(exist_ok=True)
        srcdiff = executable_copy(tools, srcdiff_name)
        srcmove = executable_copy(tools, "srcmove-valid-archive")
        return run_staged_repository_benchmark(
            data_root=root / "benchmark-data",
            series="fixture-series",
            case_name="fixture-repository",
            original=original,
            modified=modified,
            source={
                "repository": "fixture",
                "old_commit": "a" * 40,
                "new_commit": "b" * 40,
            },
            srcdiff=srcdiff,
            srcmove=srcmove,
            srcdiff_timeout_seconds=2.0,
            srcmove_timeout_seconds=2.0,
            use_position=False,
            use_archive=True,
            source_encoding="UTF-8",
            excluded_suffixes=[],
        )

    def test_repeated_benchmarks_reuse_inputs_and_append_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first, first_index = self.run_benchmark(root)
            first_bytes = first_index.read_bytes()
            second, second_index = self.run_benchmark(root)

            self.assertEqual(first["status"], "completed")
            self.assertEqual(second["status"], "completed")
            self.assertTrue(
                first["input_snapshot_id"].startswith("input-snapshot-sha256-")
            )
            self.assertEqual(first["input_snapshot_id"], second["input_snapshot_id"])
            self.assertEqual(first["corpus_id"], second["corpus_id"])
            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertNotEqual(first_index, second_index)
            self.assertEqual(first_index.read_bytes(), first_bytes)

            data_root = root / "benchmark-data"
            self.assertEqual(len(list((data_root / "input-snapshots").iterdir())), 1)
            self.assertEqual(len(list((data_root / "corpora").iterdir())), 1)
            self.assertEqual(len(list((data_root / "runs").iterdir())), 2)
            self.assertTrue((data_root / first["run_manifest"]).is_file())
            self.assertTrue((data_root / second["run_manifest"]).is_file())

            summary = first_index.parent / "summary.csv"
            with summary.open(encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertIn("input_snapshot_id", rows[0])
            self.assertEqual({row["status"] for row in rows}, {"completed"})
            self.assertTrue(all(row["srcdiff_seconds"] for row in rows))
            self.assertTrue(all(row["srcmove_seconds"] for row in rows))

    def test_srcdiff_failure_is_saved_without_a_srcmove_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            entry, index_path = self.run_benchmark(
                root, srcdiff_name="srcdiff-invalid-structure"
            )

            self.assertEqual(entry["status"], "srcdiff_failed")
            self.assertNotIn("run_id", entry)
            self.assertTrue(index_path.is_file())
            saved = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved["srcdiff_attempt"]["xml"]["status"], "invalid_structure"
            )
            data_root = root / "benchmark-data"
            self.assertFalse((data_root / "runs").exists())
            self.assertEqual(
                len(list((data_root / "attempts").glob("attempt-*/attempt.json"))),
                1,
            )

    def test_rejects_unsafe_series_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            original, modified = source_pair(root)
            tools = root / "tools"
            tools.mkdir()
            tool = executable_copy(tools, "valid-archive")
            with self.assertRaisesRegex(ValueError, "series must start"):
                run_staged_repository_benchmark(
                    data_root=root / "benchmark-data",
                    series="../escape",
                    case_name="fixture",
                    original=original,
                    modified=modified,
                    source={"repository": "fixture"},
                    srcdiff=tool,
                    srcmove=tool,
                    srcdiff_timeout_seconds=2.0,
                    srcmove_timeout_seconds=2.0,
                    use_position=False,
                    use_archive=True,
                    source_encoding="UTF-8",
                    excluded_suffixes=[],
                )


if __name__ == "__main__":
    unittest.main()
