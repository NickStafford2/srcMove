from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_TOOL = REPO_ROOT / "tests" / "fixtures" / "benchmark" / "fake_tool.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.corpus import create_preparation, generate_corpus, run_corpus
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
    def test_content_identity_survives_a_different_generated_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            original, modified = source_pair(root)
            srcdiff = executable_copy(root, "srcdiff-valid-archive")
            preparation_ids = []
            corpus_ids = []

            for generated_name in ("generated-one", "generated-two"):
                generated = root / generated_name
                adapter = RepositoryAdapter(
                    case_id="tiny", original=original, modified=modified
                )
                _, preparation = create_preparation(
                    data_root=generated,
                    adapter=adapter,
                    source={"repository": "fixture", "old": "a", "new": "b"},
                )
                _, corpus = generate_corpus(
                    data_root=generated,
                    preparation=preparation["preparation_id"],
                    srcdiff=srcdiff,
                    timeout_seconds=2.0,
                )
                preparation_ids.append(preparation["preparation_id"])
                corpus_ids.append(corpus["corpus_id"])

            self.assertEqual(preparation_ids[0], preparation_ids[1])
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
            _, preparation = create_preparation(
                data_root=generated,
                adapter=adapter,
                source={"repository": "fixture", "old": "a", "new": "b"},
            )
            corpus_dir, corpus = generate_corpus(
                data_root=generated,
                preparation=preparation["preparation_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
            )

            shutil.rmtree(root / "source")
            shutil.rmtree(generated / "preparations")
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
            _, preparation = create_preparation(
                data_root=generated,
                adapter=adapter,
                source={"repository": "fixture", "old": "a", "new": "b"},
            )

            corpus_dir, corpus = generate_corpus(
                data_root=generated,
                preparation=preparation["preparation_id"],
                srcdiff=srcdiff,
                timeout_seconds=2.0,
            )

            self.assertEqual(corpus["cases"][0]["generation_status"], "failed")
            self.assertEqual(corpus["cases"][0]["xml"]["status"], "valid")
            self.assertEqual(
                corpus["counts"], {"selected": 1, "accepted": 0, "failed": 1}
            )
            self.assertEqual(list(corpus_dir.rglob("input.srcdiff.xml")), [])
            attempt_records = list((generated / "attempts").glob("*/attempt.json"))
            self.assertEqual(len(attempt_records), 1)

    def test_mutated_preparation_or_corpus_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            generated = root / "generated"
            original, modified = source_pair(root)
            srcdiff = executable_copy(root, "srcdiff-valid-archive")
            srcmove = executable_copy(root, "srcmove-valid-archive")
            adapter = RepositoryAdapter(
                case_id="tiny", original=original, modified=modified
            )
            preparation_dir, preparation = create_preparation(
                data_root=generated,
                adapter=adapter,
                source={"repository": "fixture", "old": "a", "new": "b"},
            )
            prepared_original = (
                preparation_dir
                / preparation["cases"][0]["original_path"]
                / "sample.cpp"
            )
            original_bytes = prepared_original.read_bytes()
            prepared_original.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                generate_corpus(
                    data_root=generated,
                    preparation=preparation["preparation_id"],
                    srcdiff=srcdiff,
                    timeout_seconds=2.0,
                )

            prepared_original.write_bytes(original_bytes)
            corpus_dir, corpus = generate_corpus(
                data_root=generated,
                preparation=preparation["preparation_id"],
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
