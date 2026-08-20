from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_TOOL = REPO_ROOT / "tests" / "fixtures" / "benchmark" / "fake_tool.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.repositories.run_case import (
    ensure_repo,
    resolve_requested_commits,
    run_staged_repository_benchmark,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def create_remote(root: Path) -> tuple[Path, Path, str]:
    source = root / "source"
    source.mkdir()
    git(source, "init", "--initial-branch=main")
    git(source, "config", "user.name", "Benchmark Test")
    git(source, "config", "user.email", "benchmark@example.invalid")
    (source / "sample.cpp").write_text("int first;\n", encoding="utf-8")
    git(source, "add", "sample.cpp")
    git(source, "commit", "-m", "first")
    first_commit = git(source, "rev-parse", "HEAD")

    remote = root / "remote.git"
    subprocess.run(
        ["git", "clone", "--bare", str(source), str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(source, "remote", "add", "origin", str(remote))
    return source, remote, first_commit


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
    (original / "unsupported.py").write_text("before = 1\n", encoding="utf-8")
    (modified / "unsupported.py").write_text("after = 1\n", encoding="utf-8")
    return original, modified


class RepositoryBenchmarkTests(unittest.TestCase):
    def test_missing_repository_cache_is_cloned_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, remote, first_commit = create_remote(root)
            cache = root / "cache" / "repo"

            updated = ensure_repo(
                str(remote),
                cache,
                offline=False,
                update=False,
            )

            self.assertTrue(updated)
            self.assertEqual(git(cache, "rev-parse", "HEAD"), first_commit)

    def test_offline_mode_rejects_missing_repository_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Path(temporary_directory) / "missing" / "repo"

            with self.assertRaisesRegex(RuntimeError, "missing in offline mode"):
                ensure_repo(
                    "unused",
                    cache,
                    offline=True,
                    update=False,
                )

    def test_missing_revision_is_fetched_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source, remote, first_commit = create_remote(root)
            cache = root / "cache" / "repo"
            ensure_repo(str(remote), cache, offline=False, update=False)

            (source / "sample.cpp").write_text("int second;\n", encoding="utf-8")
            git(source, "add", "sample.cpp")
            git(source, "commit", "-m", "second")
            second_commit = git(source, "rev-parse", "HEAD")
            git(source, "push", "origin", "main")

            resolved = resolve_requested_commits(
                cache,
                first_commit,
                second_commit,
                offline=False,
                repository_updated=False,
            )

            self.assertEqual(resolved, (first_commit, second_commit))

    def test_offline_mode_does_not_fetch_a_missing_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            _, remote, first_commit = create_remote(root)
            cache = root / "cache" / "repo"
            ensure_repo(str(remote), cache, offline=False, update=False)

            with self.assertRaisesRegex(RuntimeError, "unavailable.*offline"):
                resolve_requested_commits(
                    cache,
                    first_commit,
                    "f" * 40,
                    offline=True,
                    repository_updated=False,
                )

    def run_benchmark(
        self,
        root: Path,
        *,
        srcdiff_name: str = "srcdiff-valid-archive",
        index_series: bool = True,
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
            index_series=index_series,
        )

    def test_history_style_run_skips_standalone_repository_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            entry, index_path = self.run_benchmark(root, index_series=False)

            self.assertEqual(entry["status"], "completed")
            self.assertIsNone(index_path)
            self.assertFalse((root / "benchmark-data" / "repository-runs").exists())
            self.assertNotIn("repository_index_seconds", entry["timings"])

    def test_repeated_benchmarks_reuse_inputs_and_append_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first, first_index = self.run_benchmark(root)
            first_bytes = first_index.read_bytes()
            second, second_index = self.run_benchmark(root)

            self.assertEqual(first["status"], "completed")
            self.assertEqual(second["status"], "completed")
            self.assertEqual(first["configuration"]["excluded_suffixes"], [".py"])
            self.assertTrue(
                first["input_snapshot_id"].startswith("input-snapshot-sha256-")
            )
            self.assertEqual(first["input_snapshot_id"], second["input_snapshot_id"])
            self.assertEqual(first["corpus_id"], second["corpus_id"])
            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertNotEqual(first_index, second_index)
            self.assertEqual(first_index.read_bytes(), first_bytes)
            self.assertIn("srcdiff_execution_seconds", first["timings"])
            self.assertNotIn("srcdiff_cached_execution_seconds", first["timings"])
            self.assertIn("srcdiff_cached_execution_seconds", second["timings"])
            self.assertNotIn("srcdiff_execution_seconds", second["timings"])
            self.assertGreater(second["timings"]["srcdiff_stage_wall_seconds"], 0)
            self.assertGreater(second["timings"]["pipeline_wall_seconds"], 0)
            for timing_name in (
                "srcdiff_input_snapshot_verification_seconds",
                "srcdiff_attempt_recovery_seconds",
                "srcdiff_executable_observation_seconds",
                "srcdiff_attempt_reconciliation_seconds",
                "srcdiff_corpus_verification_seconds",
                "srcmove_corpus_verification_seconds",
                "srcmove_observation_seconds",
                "srcmove_attempt_reconciliation_seconds",
                "repository_index_seconds",
            ):
                self.assertIn(timing_name, second["timings"])
                self.assertGreaterEqual(second["timings"][timing_name], 0)

            data_root = root / "benchmark-data"
            self.assertEqual(len(list((data_root / "input-snapshots").iterdir())), 1)
            self.assertEqual(len(list((data_root / "corpora").iterdir())), 1)
            self.assertEqual(len(list((data_root / "runs").iterdir())), 2)
            self.assertTrue((data_root / first["run_manifest"]).is_file())
            self.assertTrue((data_root / second["run_manifest"]).is_file())
            snapshot_manifest = json.loads(
                (data_root / first["input_snapshot_manifest"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                snapshot_manifest["filter_configuration"]["excluded_suffixes"],
                [".py"],
            )
            self.assertEqual(snapshot_manifest["counts"]["excluded_files"], 2)

            summary = first_index.parent / "summary.csv"
            with summary.open(encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertIn("input_snapshot_id", rows[0])
            self.assertEqual({row["status"] for row in rows}, {"completed"})
            self.assertTrue(all(row["srcdiff_seconds"] for row in rows))
            self.assertTrue(all(row["srcmove_seconds"] for row in rows))
            self.assertTrue(rows[0]["srcdiff_execution_seconds"])
            self.assertFalse(rows[0]["srcdiff_cached_execution_seconds"])
            self.assertFalse(rows[1]["srcdiff_execution_seconds"])
            self.assertTrue(rows[1]["srcdiff_cached_execution_seconds"])

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
