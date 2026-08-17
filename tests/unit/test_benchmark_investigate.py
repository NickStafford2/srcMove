from __future__ import annotations

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

from benchmarks.corpus import create_input_snapshot, generate_corpus
from benchmarks.repositories.adapter import RepositoryAdapter


def executable_copy(root: Path, name: str) -> Path:
    destination = root / name
    shutil.copy2(FAKE_TOOL, destination)
    destination.chmod(0o755)
    return destination


class InvestigationTests(unittest.TestCase):
    def test_failed_attempt_can_be_replayed_and_reduced_from_input_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data_root = root / "generated"
            original = root / "source" / "original"
            modified = root / "source" / "modified"
            original.mkdir(parents=True)
            modified.mkdir(parents=True)
            for name in ("first.cpp", "nested/second.cpp"):
                (original / name).parent.mkdir(parents=True, exist_ok=True)
                (modified / name).parent.mkdir(parents=True, exist_ok=True)
                (original / name).write_text("int old;\n")
                (modified / name).write_text("int new;\n")
            _, input_snapshot = create_input_snapshot(
                data_root=data_root,
                adapter=RepositoryAdapter(
                    case_id="failure", original=original, modified=modified
                ),
                source={"repository": "fixture"},
            )
            failing = executable_copy(root, "srcdiff-nonzero-valid")
            valid = executable_copy(root, "srcdiff-valid-archive")
            _, corpus = generate_corpus(
                data_root=data_root,
                input_snapshot=input_snapshot["input_snapshot_id"],
                srcdiff=failing,
                timeout_seconds=2.0,
            )
            source_attempt = corpus["cases"][0]["attempt_id"]

            replay = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "benchmarks" / "investigate.py"),
                    "--data-root",
                    str(data_root),
                    "replay",
                    source_attempt,
                    "--srcdiff",
                    str(valid),
                    "--relative-path",
                    "nested/second.cpp",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(replay.returncode, 0, replay.stderr)
            replay_directory = Path(
                next(
                    line.removeprefix("directory=")
                    for line in replay.stdout.splitlines()
                    if line.startswith("directory=")
                )
            )
            replay_manifest = json.loads(
                (replay_directory / "manifest.json").read_text()
            )
            self.assertEqual(replay_manifest["selected_paths"], ["nested/second.cpp"])
            replay_attempt = json.loads(
                next(
                    (data_root / "attempts").glob(
                        f"{replay_manifest['attempts'][0]['attempt_id']}/attempt.json"
                    )
                ).read_text()
            )
            self.assertEqual(replay_attempt["parent_attempt_id"], source_attempt)

            isolate = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "benchmarks" / "investigate.py"),
                    "--data-root",
                    str(data_root),
                    "isolate",
                    source_attempt,
                    "--srcdiff",
                    str(failing),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(isolate.returncode, 1, isolate.stderr)
            isolate_directory = Path(
                next(
                    line.removeprefix("directory=")
                    for line in isolate.stdout.splitlines()
                    if line.startswith("directory=")
                )
            )
            isolate_manifest = json.loads(
                (isolate_directory / "manifest.json").read_text()
            )
            self.assertEqual(len(isolate_manifest["selected_paths"]), 1)
            self.assertGreaterEqual(len(isolate_manifest["attempts"]), 1)


if __name__ == "__main__":
    unittest.main()
