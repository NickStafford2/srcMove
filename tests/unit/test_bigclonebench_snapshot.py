from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.bigclonebench.adapter import (
    SYNTHETIC_WRAPPER_VERSION,
    CompiledBigCloneBenchAdapter,
    _type3_frame_strength,
)
from benchmarks.bigclonebench.generate import (
    SYNTHETIC_DESTINATION_PATH,
    SYNTHETIC_SOURCE_PATH,
)
from benchmarks.bigclonebench.compiled import compile_exports
from benchmarks.bigclonebench.selection import create_selection
from benchmarks.corpus import create_input_snapshot, load_input_snapshot
from tests.unit.test_bigclonebench_compiled import (
    BigCloneBenchCompiledDatasetTests,
    distinct_false_positive_row,
    pair_row,
    write_export,
)


class BigCloneBenchSnapshotTests(unittest.TestCase):
    def test_type_three_frame_strength_is_conservative_across_rows(self) -> None:
        strength, stratum = _type3_frame_strength(
            [
                {"similarity": {"line": 0.96, "token": 0.94}},
                {"similarity": {"line": 0.89, "token": 0.91}},
            ]
        )
        self.assertEqual(strength, 0.89)
        self.assertEqual(stratum, "strong")

    def compile_fixture(self, root: Path):
        fixture = BigCloneBenchCompiledDatasetTests(
            methodName="test_full_exports_skip_unneeded_global_ordering"
        )
        bce = fixture.create_bce(root)
        exports = root / "exports"
        exports.mkdir()
        type_one = pair_row()
        type_two = pair_row()
        type_two["syntactic_type"] = 2
        type_two["pair_type"] = "type-2"
        type_three = pair_row()
        type_three["syntactic_type"] = 3
        type_three["pair_type"] = "type-3"
        write_export(exports / "positive.csv", [type_one, type_two, type_three])
        false_positive = distinct_false_positive_row(bce)
        false_positive["syntactic_type"] = 3
        write_export(exports / "false.csv", [false_positive])
        compiled = compile_exports(
            bce_dir=bce,
            data_root=root / "data",
            exports={
                "positive": exports / "positive.csv",
                "known_false_positive": exports / "false.csv",
            },
            compile_scope={"fixture": "snapshot"},
        )
        return bce, compiled

    def materialize(self, root: Path, pair_set: str):
        bce, compiled = self.compile_fixture(root)
        selection_dir, selection, _ = create_selection(
            compiled,
            data_root=root / "data",
            pair_set=pair_set,
            mode="census",
            role="tuning" if pair_set == "type3" else "evaluation",
        )
        # Phase 3 must need neither the original H2 database nor generated cases.
        (bce / "bigclonebenchdb" / "bcb.h2.db").unlink()
        adapter = CompiledBigCloneBenchAdapter(
            data_root=root / "data", selection=selection_dir.name
        )
        snapshot = create_input_snapshot(
            data_root=root / "data",
            adapter=adapter,
            source=adapter.source_manifest(),
        )
        return compiled, selection, snapshot

    def test_materializes_type_one_directly_and_reuses_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled, selection, snapshot = self.materialize(root, "type1")

            self.assertEqual(snapshot.manifest["counts"]["selected"], 1)
            case = snapshot.manifest["cases"][0]
            metadata = case["metadata"]
            self.assertEqual(metadata["syntactic_type"], 1)
            self.assertEqual(metadata["selection_id"], selection["selection_id"])
            self.assertEqual(metadata["compiled_dataset_id"], compiled.dataset_id)
            self.assertEqual(
                metadata["synthetic_wrapper_version"], SYNTHETIC_WRAPPER_VERSION
            )
            self.assertEqual(len(metadata["selection_frame"]["rows"]), 1)

            original_source = (
                snapshot.directory
                / case["original_path"]
                / SYNTHETIC_SOURCE_PATH
            )
            modified_destination = (
                snapshot.directory
                / case["modified_path"]
                / SYNTHETIC_DESTINATION_PATH
            )
            self.assertEqual(
                {value["path"] for value in case["original"]["files"]},
                {
                    SYNTHETIC_SOURCE_PATH.as_posix(),
                    SYNTHETIC_DESTINATION_PATH.as_posix(),
                },
            )
            self.assertEqual(
                {value["path"] for value in case["modified"]["files"]},
                {
                    SYNTHETIC_SOURCE_PATH.as_posix(),
                    SYNTHETIC_DESTINATION_PATH.as_posix(),
                },
            )
            self.assertIn("class BCBMove", original_source.read_text())
            self.assertIn(
                metadata["expected"]["from_generated_text"].strip(),
                original_source.read_text(),
            )
            self.assertIn(
                metadata["expected"]["to_generated_text"].strip(),
                modified_destination.read_text(),
            )
            self.assertNotEqual(
                metadata["fragment_one"]["sha256"],
                metadata["fragment_two"]["sha256"],
            )
            self.assertFalse(original_source.stat().st_mode & 0o222)
            load_input_snapshot(root / "data", snapshot.snapshot_id)

            adapter = CompiledBigCloneBenchAdapter(
                data_root=root / "data", selection=selection["selection_id"]
            )
            disposition = []
            reused = create_input_snapshot(
                data_root=root / "data",
                adapter=adapter,
                source=adapter.source_manifest(),
                status_callback=disposition.append,
            )
            self.assertEqual(reused.snapshot_id, snapshot.snapshot_id)
            self.assertEqual(disposition, ["reused"])

    def test_type_two_metadata_uses_strict_type_two_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, _, snapshot = self.materialize(Path(temporary), "type2")
            metadata = snapshot.manifest["cases"][0]["metadata"]
            self.assertEqual(metadata["clone_type"], "type2")
            self.assertEqual(metadata["syntactic_type"], 2)
            self.assertEqual(metadata["expected"]["move_count"], 1)

    def test_type_three_materializes_as_a_positive_case(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, _, snapshot = self.materialize(Path(temporary), "type3")
            metadata = snapshot.manifest["cases"][0]["metadata"]
            self.assertEqual(metadata["case_kind"], "positive")
            self.assertEqual(metadata["clone_type"], "type3")
            self.assertEqual(metadata["syntactic_type"], 3)
            self.assertEqual(metadata["syntactic_types"], [3])
            self.assertEqual(metadata["expected"]["move_count"], 1)
            self.assertEqual(metadata["type3_both_similarity"], 1.0)
            self.assertEqual(metadata["type3_strength_stratum"], "very_strong")

    def test_known_false_positive_uses_negative_oracle_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _, selection, snapshot = self.materialize(
                Path(temporary), "known-false-positive"
            )
            metadata = snapshot.manifest["cases"][0]["metadata"]
            self.assertEqual(metadata["case_kind"], "known_false_positive")
            self.assertEqual(metadata["clone_type"], "known_false_positive")
            self.assertEqual(metadata["syntactic_type"], 3)
            self.assertEqual(metadata["syntactic_types"], [3])
            self.assertEqual(metadata["expected"]["move_count"], 0)
            self.assertEqual(
                snapshot.manifest["source"]["selection"]["selection"]["id"],
                selection["selection_id"],
            )

    def test_selected_fragment_corruption_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, compiled = self.compile_fixture(root)
            selection_dir, _, _ = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="type1",
                mode="census",
                role="tuning",
            )
            frame = json.loads((selection_dir / "frames.jsonl").read_text().splitlines()[0])
            fragment_sha = frame["direction"]["original_fragment_sha256"]
            fragment = (
                compiled.directory
                / "fragments"
                / fragment_sha[:2]
                / f"{fragment_sha}.java"
            )
            fragment.write_text("corrupt\n")
            adapter = CompiledBigCloneBenchAdapter(
                data_root=root / "data", selection=selection_dir
            )
            with self.assertRaisesRegex(ValueError, "fragment checksum mismatch"):
                create_input_snapshot(
                    data_root=root / "data",
                    adapter=adapter,
                    source=adapter.source_manifest(),
                )


if __name__ == "__main__":
    unittest.main()
