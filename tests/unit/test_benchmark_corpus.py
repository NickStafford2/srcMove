from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Sequence
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_TOOL = REPO_ROOT / "tests" / "fixtures" / "benchmark" / "fake_tool.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.corpus import create_input_snapshot, generate_corpus, run_corpus
from benchmarks.contracts import InputPair
from benchmarks.repositories.adapter import RepositoryAdapter


def executable_copy(root: Path, name: str) -> Path:
    destination = root / name
    shutil.copy2(FAKE_TOOL, destination)
    destination.chmod(0o755)
    return destination


def source_pair(root: Path) -> tuple[Path, Path]:
    original = root / "source" / "original"
    modified = root / "source" / "modified"
    original.mkdir(parents=True)
    modified.mkdir(parents=True)
    (original / "sample.cpp").write_text("int first();\n", encoding="utf-8")
    (modified / "sample.cpp").write_text("int second();\n", encoding="utf-8")
    return original, modified


class CorpusPipelineTests(unittest.TestCase):
    def test_generation_reports_running_then_reused_activity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            generated = root / "generated"
            original, modified = source_pair(root)
            srcdiff = executable_copy(root, "srcdiff-valid-archive")
            _, input_snapshot = create_input_snapshot(
                data_root=generated,
                adapter=RepositoryAdapter(
                    case_id="tiny", original=original, modified=modified
                ),
                source={"repository": "fixture"},
            )

            first_activity: list[tuple[str, str]] = []
            generate_corpus(
                data_root=generated,
                input_snapshot=input_snapshot["input_snapshot_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
                activity_callback=lambda activity, case_id: first_activity.append(
                    (activity, case_id)
                ),
            )
            second_activity: list[tuple[str, str]] = []
            generate_corpus(
                data_root=generated,
                input_snapshot=input_snapshot["input_snapshot_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
                activity_callback=lambda activity, case_id: second_activity.append(
                    (activity, case_id)
                ),
            )

            self.assertEqual(
                first_activity, [("running", "tiny"), ("accepted", "tiny")]
            )
            self.assertEqual(second_activity, [("reused", "tiny")])

    def test_generation_continues_after_a_case_failure(self) -> None:
        class Adapter:
            name = "fixture-failure-batch"
            version = 1

            def __init__(self, cases: Sequence[InputPair]) -> None:
                self.cases = cases

            def input_pairs(self) -> Sequence[InputPair]:
                return self.cases

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            cases = []
            for case_id in ("fails", "passes"):
                original = root / case_id / "original"
                modified = root / case_id / "modified"
                original.mkdir(parents=True)
                modified.mkdir(parents=True)
                (original / "sample.cpp").write_text("int old;\n")
                (modified / "sample.cpp").write_text("int new;\n")
                cases.append(InputPair(case_id, original, modified))
            generated = root / "generated"
            _, input_snapshot = create_input_snapshot(
                data_root=generated,
                adapter=Adapter(cases),
                source={"repository": "fixture"},
            )
            srcdiff = root / "srcdiff-case-aware"
            srcdiff.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\nfrom pathlib import Path\n"
                "out=Path(sys.argv[sys.argv.index('-o')+1])\n"
                "out.write_text(\"<unit xmlns='http://www.srcML.org/srcML/src' "
                "xmlns:diff='http://www.srcML.org/srcDiff'>"
                "<unit/></unit>\")\n"
                "raise SystemExit(23 if '/fails/' in sys.argv[-4] else 0)\n"
            )
            srcdiff.chmod(0o755)

            _, corpus = generate_corpus(
                data_root=generated,
                input_snapshot=input_snapshot["input_snapshot_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
            )

            self.assertEqual(corpus["counts"]["failed"], 1)
            self.assertEqual(corpus["counts"]["accepted"], 1)
            self.assertEqual(
                len(list((generated / "attempts").glob("*/attempt.json"))), 2
            )

    def test_srcmove_run_retry_keeps_run_and_attempt_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            generated = root / "generated"
            original, modified = source_pair(root)
            srcdiff = executable_copy(root, "srcdiff-valid-archive")
            _, input_snapshot = create_input_snapshot(
                data_root=generated,
                adapter=RepositoryAdapter(
                    case_id="tiny", original=original, modified=modified
                ),
                source={"repository": "fixture"},
            )
            corpus_dir, _ = generate_corpus(
                data_root=generated,
                input_snapshot=input_snapshot["input_snapshot_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
            )
            srcmove = root / "srcmove-retry"
            mode = srcmove.with_suffix(".mode")
            srcmove.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\nfrom pathlib import Path\n"
                "mode=Path(__file__).with_suffix('.mode').read_text().strip()\n"
                "if mode == 'fail': raise SystemExit(23)\n"
                "Path(sys.argv[2]).write_text(\"<unit "
                "xmlns='http://www.srcML.org/srcML/src' "
                "xmlns:diff='http://www.srcML.org/srcDiff'>"
                "<unit/></unit>\")\n"
                "Path(sys.argv[sys.argv.index('--results')+1]).write_text('{}')\n"
            )
            srcmove.chmod(0o755)
            mode.write_text("fail")
            run_dir, failed = run_corpus(
                data_root=generated,
                corpus=corpus_dir,
                srcmove=srcmove,
                timeout_seconds=2.0,
            )
            parent = failed["cases"][0]["attempt_id"]
            mode.write_text("success")
            resumed_dir, resumed = run_corpus(
                data_root=generated,
                corpus=corpus_dir,
                srcmove=srcmove,
                timeout_seconds=2.0,
                resume_run=failed["run_id"],
                retry_failed=True,
            )

            self.assertEqual(run_dir, resumed_dir)
            self.assertEqual(resumed["run_id"], failed["run_id"])
            self.assertEqual(resumed["cases"][0]["parent_attempt_id"], parent)
            self.assertEqual(resumed["cases"][0]["retry_ordinal"], 1)
            self.assertEqual(resumed["cases"][0]["status"], "completed")
            self.assertEqual(
                len(list((run_dir / "attempts").glob("*/attempt.json"))), 2
            )

    def test_input_snapshot_filter_is_recorded_and_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            original, modified = source_pair(root)
            (original / "unsupported.py").write_text("print('old')\n")
            (modified / "unsupported.py").write_text("print('new')\n")
            adapter = RepositoryAdapter(
                case_id="tiny", original=original, modified=modified
            )

            input_snapshot_dir, manifest = create_input_snapshot(
                data_root=root / "generated",
                adapter=adapter,
                source={"repository": "fixture"},
                filter_configuration={"excluded_suffixes": ["py"]},
            )

            self.assertTrue((original / "unsupported.py").is_file())
            self.assertTrue(
                manifest["input_snapshot_id"].startswith("input-snapshot-sha256-")
            )
            self.assertEqual(input_snapshot_dir.parent.name, "input-snapshots")
            self.assertEqual(
                manifest["filter_configuration"]["excluded_suffixes"], [".py"]
            )
            self.assertEqual(manifest["counts"]["excluded_files"], 2)
            self.assertFalse(
                (
                    input_snapshot_dir
                    / manifest["cases"][0]["original_path"]
                    / "unsupported.py"
                ).exists()
            )

    def test_generation_resumes_completed_cases_and_retries_with_lineage(self) -> None:
        class Adapter:
            name = "fixture-batch"
            version = 1

            def __init__(self, cases: Sequence[InputPair]) -> None:
                self.cases = cases

            def input_pairs(self) -> Sequence[InputPair]:
                return self.cases

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            generated = root / "generated"
            pairs = []
            for case_id in ("one", "two"):
                original = root / case_id / "original"
                modified = root / case_id / "modified"
                original.mkdir(parents=True)
                modified.mkdir(parents=True)
                (original / "sample.cpp").write_text("int old;\n")
                (modified / "sample.cpp").write_text("int new;\n")
                pairs.append(InputPair(case_id, original, modified))
            _, input_snapshot = create_input_snapshot(
                data_root=generated,
                adapter=Adapter(pairs),
                source={"repository": "fixture"},
            )
            srcdiff = executable_copy(root, "srcdiff-valid-archive")

            from benchmarks import corpus as corpus_module

            real_execute_attempt = corpus_module.execute_attempt
            invocations = 0

            def interrupt_second_attempt(**arguments):
                nonlocal invocations
                invocations += 1
                if invocations == 2:
                    raise KeyboardInterrupt()
                return real_execute_attempt(**arguments)

            with mock.patch.object(
                corpus_module, "execute_attempt", side_effect=interrupt_second_attempt
            ):
                with self.assertRaises(KeyboardInterrupt):
                    generate_corpus(
                        data_root=generated,
                        input_snapshot=input_snapshot["input_snapshot_id"],
                        srcdiff=srcdiff,
                        timeout_seconds=2.0,
                    )
            _, resumed = generate_corpus(
                data_root=generated,
                input_snapshot=input_snapshot["input_snapshot_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
            )

            self.assertEqual(resumed["counts"]["accepted"], 2)
            self.assertEqual(
                len(list((generated / "attempts").glob("*/attempt.json"))), 2
            )

            retry_tool = root / "srcdiff-retry"
            retry_mode = retry_tool.with_suffix(".mode")
            retry_tool.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\nfrom pathlib import Path\n"
                "mode=Path(__file__).with_suffix('.mode').read_text().strip()\n"
                "out=Path(sys.argv[sys.argv.index('-o')+1])\n"
                "out.write_text(\"<unit xmlns='http://www.srcML.org/srcML/src' "
                "xmlns:diff='http://www.srcML.org/srcDiff'>"
                "<unit/></unit>\")\n"
                "raise SystemExit(23 if mode == 'fail' else 0)\n"
            )
            retry_tool.chmod(0o755)
            retry_mode.write_text("fail")
            _, failed = generate_corpus(
                data_root=root / "retry-generated",
                input_snapshot=create_input_snapshot(
                    data_root=root / "retry-generated",
                    adapter=Adapter([pairs[0]]),
                    source={"repository": "fixture"},
                )[1]["input_snapshot_id"],
                srcdiff=retry_tool,
                timeout_seconds=2.0,
            )
            parent = failed["cases"][0]["attempt_id"]
            retry_mode.write_text("success")
            _, retried = generate_corpus(
                data_root=root / "retry-generated",
                input_snapshot=failed["input_snapshot_id"],
                srcdiff=retry_tool,
                timeout_seconds=2.0,
                retry_failed=True,
            )
            self.assertEqual(retried["cases"][0]["parent_attempt_id"], parent)
            self.assertEqual(retried["cases"][0]["retry_ordinal"], 1)
            self.assertEqual(retried["cases"][0]["generation_status"], "accepted")

    def test_content_identity_survives_a_different_generated_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            original, modified = source_pair(root)
            srcdiff = executable_copy(root, "srcdiff-valid-archive")
            input_snapshot_ids = []
            corpus_ids = []

            for generated_name in ("generated-one", "generated-two"):
                generated = root / generated_name
                adapter = RepositoryAdapter(
                    case_id="tiny", original=original, modified=modified
                )
                _, input_snapshot = create_input_snapshot(
                    data_root=generated,
                    adapter=adapter,
                    source={"repository": "fixture", "old": "a", "new": "b"},
                )
                _, corpus = generate_corpus(
                    data_root=generated,
                    input_snapshot=input_snapshot["input_snapshot_id"],
                    srcdiff=srcdiff,
                    timeout_seconds=2.0,
                )
                input_snapshot_ids.append(input_snapshot["input_snapshot_id"])
                corpus_ids.append(corpus["corpus_id"])

            self.assertEqual(input_snapshot_ids[0], input_snapshot_ids[1])
            self.assertEqual(corpus_ids[0], corpus_ids[1])

    def test_corpus_replay_needs_neither_sources_nor_srcdiff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            generated = root / "generated"
            original, modified = source_pair(root)
            srcdiff = executable_copy(root, "srcdiff-valid-archive")
            srcmove = executable_copy(root, "srcmove-valid-archive")
            adapter = RepositoryAdapter(
                case_id="tiny", original=original, modified=modified
            )
            _, input_snapshot = create_input_snapshot(
                data_root=generated,
                adapter=adapter,
                source={"repository": "fixture", "old": "a", "new": "b"},
            )
            corpus_dir, corpus = generate_corpus(
                data_root=generated,
                input_snapshot=input_snapshot["input_snapshot_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
            )

            shutil.rmtree(root / "source")
            shutil.rmtree(generated / "input-snapshots")
            srcdiff.unlink()
            first_dir, first = run_corpus(
                data_root=generated,
                corpus=corpus_dir,
                srcmove=srcmove,
                timeout_seconds=2.0,
            )
            second_dir, second = run_corpus(
                data_root=generated,
                corpus=corpus["corpus_id"],
                srcmove=srcmove,
                timeout_seconds=2.0,
            )

            self.assertEqual(first["cases"][0]["status"], "completed")
            self.assertEqual(second["cases"][0]["status"], "completed")
            self.assertEqual(
                first["counts"],
                {
                    "corpus_selected": 1,
                    "corpus_accepted": 1,
                    "corpus_failed": 0,
                    "executed": 1,
                    "completed": 1,
                    "failed": 0,
                },
            )
            self.assertNotEqual(first["run_id"], second["run_id"])
            self.assertTrue((first_dir / "run.json").is_file())
            self.assertTrue((second_dir / "run.json").is_file())

    def test_failed_srcdiff_output_is_never_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            generated = root / "generated"
            original, modified = source_pair(root)
            srcdiff = executable_copy(root, "srcdiff-nonzero-valid")
            adapter = RepositoryAdapter(
                case_id="tiny", original=original, modified=modified
            )
            _, input_snapshot = create_input_snapshot(
                data_root=generated,
                adapter=adapter,
                source={"repository": "fixture", "old": "a", "new": "b"},
            )

            corpus_dir, corpus = generate_corpus(
                data_root=generated,
                input_snapshot=input_snapshot["input_snapshot_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
            )

            self.assertEqual(corpus["cases"][0]["generation_status"], "failed")
            self.assertEqual(corpus["cases"][0]["xml"]["status"], "valid")
            self.assertEqual(
                corpus["counts"],
                {"selected": 1, "accepted": 0, "failed": 1},
            )
            self.assertEqual(list(corpus_dir.rglob("input.srcdiff.xml")), [])
            attempt_records = list((generated / "attempts").glob("*/attempt.json"))
            self.assertEqual(len(attempt_records), 1)

    def test_mutated_input_snapshot_or_corpus_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            generated = root / "generated"
            original, modified = source_pair(root)
            srcdiff = executable_copy(root, "srcdiff-valid-archive")
            srcmove = executable_copy(root, "srcmove-valid-archive")
            adapter = RepositoryAdapter(
                case_id="tiny", original=original, modified=modified
            )
            input_snapshot_dir, input_snapshot = create_input_snapshot(
                data_root=generated,
                adapter=adapter,
                source={"repository": "fixture", "old": "a", "new": "b"},
            )
            snapshot_original = (
                input_snapshot_dir
                / input_snapshot["cases"][0]["original_path"]
                / "sample.cpp"
            )
            original_bytes = snapshot_original.read_bytes()
            snapshot_original.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                generate_corpus(
                    data_root=generated,
                    input_snapshot=input_snapshot["input_snapshot_id"],
                    srcdiff=srcdiff,
                    timeout_seconds=2.0,
                )

            snapshot_original.write_bytes(original_bytes)
            corpus_dir, corpus = generate_corpus(
                data_root=generated,
                input_snapshot=input_snapshot["input_snapshot_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
            )
            corpus_input = corpus_dir / corpus["cases"][0]["input_path"]
            corpus_input.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                run_corpus(
                    data_root=generated,
                    corpus=corpus["corpus_id"],
                    srcmove=srcmove,
                    timeout_seconds=2.0,
                )


if __name__ == "__main__":
    unittest.main()
