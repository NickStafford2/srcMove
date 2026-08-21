from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.bigclonebench.compiled import compile_exports
from benchmarks.bigclonebench.selection import (
    _sample_rank,
    create_selection,
    load_selection,
)
from benchmarks.provenance import sha256_file
from tests.unit.test_bigclonebench_compiled import (
    BigCloneBenchCompiledDatasetTests,
    pair_row,
    write_export,
)


class BigCloneBenchSelectionTests(unittest.TestCase):
    def compile_fixture(self, root: Path):
        fixture = BigCloneBenchCompiledDatasetTests(
            methodName="test_full_exports_skip_unneeded_global_ordering"
        )
        bce = fixture.create_bce(root)
        exports = root / "exports"
        exports.mkdir()
        type1_forward = pair_row()
        type1_reverse = pair_row(reverse=True)
        type2 = pair_row()
        type2["syntactic_type"] = 2
        type2["pair_type"] = "type-2"
        type2["min_tokens"] = 40
        false_positive = pair_row(reverse=True, pair_type="false")
        write_export(
            exports / "positive.csv",
            [type1_forward, type1_forward, type1_reverse, type2],
        )
        write_export(exports / "false.csv", [false_positive])
        return compile_exports(
            bce_dir=bce,
            data_root=root / "data",
            exports={
                "positive": exports / "positive.csv",
                "known_false_positive": exports / "false.csv",
            },
            compile_scope={"fixture": "selection"},
        )

    def test_census_dedupes_direction_and_preserves_rows_and_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = self.compile_fixture(root)
            catalog = compiled.directory / "catalog.sqlite"
            catalog_sha = sha256_file(catalog)

            directory, manifest, reused = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="type1",
                mode="census",
                role="evaluation",
            )

            self.assertFalse(reused)
            self.assertEqual(sha256_file(catalog), catalog_sha)
            self.assertEqual(manifest["request"]["eligibility"]["minimum_tokens"], None)
            self.assertEqual(manifest["counts"]["eligible_frames"], 1)
            self.assertEqual(manifest["counts"]["selected_catalog_rows"], 2)
            self.assertEqual(manifest["counts"]["selected_source_rows"], 3)
            self.assertEqual(
                manifest["counts"]["reverse_direction_excluded_catalog_rows"], 1
            )
            self.assertEqual(manifest["label_conflicts"]["frames"], 1)

            frames = [
                json.loads(line)
                for line in (directory / "frames.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(frames), 1)
            frame = frames[0]
            self.assertEqual(len(frame["rows"]), 2)
            self.assertEqual(frame["source_row_multiplicity"], 3)
            self.assertEqual(len(frame["functionality_ids"]), 1)
            self.assertEqual(len(frame["function_ids"]), 2)
            self.assertTrue(frame["generated_input_id"].startswith("bcb-generated-input-sha256-"))
            self.assertEqual(len(frame["reverse_direction_exclusions"]), 1)
            for row in frame["rows"]:
                self.assertIn("similarity", row)
                self.assertIn("size", row)
                self.assertIn("tokens", row)
                self.assertIn("judgment", row)
                self.assertIn("function_one", row)

            conflict = json.loads(
                (directory / "label-conflicts.jsonl").read_text().splitlines()[0]
            )
            self.assertEqual(conflict["labels"], ["known_false_positive", "positive"])
            self.assertEqual(conflict["catalog_row_count"], 4)

            second_directory, second_manifest, second_reused = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="type1",
                mode="census",
                role="evaluation",
            )
            self.assertTrue(second_reused)
            self.assertEqual(second_directory, directory)
            self.assertEqual(second_manifest["selection_id"], manifest["selection_id"])
            load_selection(directory, expected_dataset_id=compiled.dataset_id)

    def test_pair_sets_and_sample_identity_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = self.compile_fixture(root)
            type1_dir, type1, _ = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="type1",
                mode="sample",
                role="tuning",
                sample_size=1,
                seed=17,
            )
            type2_dir, type2, _ = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="type2",
                mode="census",
                role="tuning",
            )
            negative_dir, negative, _ = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="known-false-positive",
                mode="census",
                role="tuning",
            )

            self.assertEqual(len({type1_dir.name, type2_dir.name, negative_dir.name}), 3)
            self.assertEqual(type1["request"]["sample"]["seed"], 17)
            self.assertEqual(type2["counts"]["selected_frames"], 1)
            self.assertEqual(negative["counts"]["selected_frames"], 1)
            self.assertEqual(type2["counts"]["eligible_source_rows_below_50_tokens"], 1)
            self.assertNotEqual(_sample_rank(1, "frame"), _sample_rank(2, "frame"))

    def test_audit_dedupe_none_retains_both_catalog_directions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = self.compile_fixture(root)
            _, manifest, _ = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="type1",
                mode="census",
                role="tuning",
                dedupe="none",
            )
            self.assertEqual(manifest["counts"]["selected_frames"], 2)
            self.assertEqual(
                manifest["counts"]["reverse_direction_excluded_catalog_rows"], 0
            )


if __name__ == "__main__":
    unittest.main()
