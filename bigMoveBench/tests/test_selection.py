from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bigMoveBench.catalog import compile_exports
from bigMoveBench.selection import (
    _equal_type3_allocation,
    _sample_rank,
    create_selection,
    load_selection,
)
from benchmarking.provenance import sha256_file
from bigMoveBench.tests.test_catalog import (
    BigCloneBenchCompiledDatasetTests,
    distinct_false_positive_row,
    pair_row,
    write_export,
)


class BigCloneBenchSelectionTests(unittest.TestCase):
    def compile_type3_fixture(self, root: Path):
        fixture = BigCloneBenchCompiledDatasetTests(
            methodName="test_full_exports_skip_unneeded_global_ordering"
        )
        bce = fixture.create_bce(root)
        exports = root / "exports"
        exports.mkdir()
        similarities = (0.96, 0.94, 0.92, 0.82, 0.62, 0.42)
        rows = []
        for index, similarity in enumerate(similarities, start=1):
            functionality = 100 + index
            first_id = 1000 + index * 2
            second_id = first_id + 1
            reduced = bce / "ijadataset" / "bcb_reduced" / str(functionality)
            (reduced / "default").mkdir(parents=True)
            (reduced / "sample").mkdir()
            (reduced / "default" / f"A{index}.java").write_text(
                f"class A{index} {{\n  void a() {{\n    callA{index}();\n  }}\n}}\n"
            )
            (reduced / "sample" / f"B{index}.java").write_text(
                f"class B{index} {{\n  void b() {{\n    callB{index}();\n  }}\n}}\n"
            )
            row = pair_row()
            row.update(
                {
                    "functionality_id": functionality,
                    "function_id_one": first_id,
                    "nameone": f"A{index}.java",
                    "function_id_two": second_id,
                    "nametwo": f"B{index}.java",
                    "syntactic_type": 3,
                    "pair_type": "type-3",
                    "similarity_line": similarity,
                    "similarity_token": similarity + 0.01,
                }
            )
            rows.append(row)
        conflicting_negative = dict(rows[0])
        conflicting_negative["pair_type"] = "false"
        write_export(exports / "positive.csv", rows)
        write_export(exports / "false.csv", [conflicting_negative])
        return compile_exports(
            bce_dir=bce,
            data_root=root / "data",
            exports={
                "positive": exports / "positive.csv",
                "known_false_positive": exports / "false.csv",
            },
            compile_scope={"fixture": "type3-strata"},
        )

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
        type3 = pair_row()
        type3["syntactic_type"] = 3
        type3["pair_type"] = "type-3"
        false_positive = distinct_false_positive_row(bce)
        write_export(
            exports / "positive.csv",
            [type1_forward, type1_forward, type1_reverse, type2, type3],
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

    def test_census_dedupes_direction_and_preserves_rows(self) -> None:
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
            self.assertEqual(manifest["label_conflicts"]["frames"], 0)

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

            second_directory, second_manifest, second_reused = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="type1",
                mode="census",
            )
            self.assertTrue(second_reused)
            self.assertEqual(second_directory, directory)
            self.assertEqual(second_manifest["selection_id"], manifest["selection_id"])
            load_selection(directory, expected_dataset_id=compiled.dataset_id)

    def test_content_label_conflicts_are_audit_only_for_every_dedupe_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = BigCloneBenchCompiledDatasetTests(
                methodName="test_full_exports_skip_unneeded_global_ordering"
            )
            bce = fixture.create_bce(root)
            exports = root / "exports"
            exports.mkdir()
            clean_positive = distinct_false_positive_row(bce)
            clean_positive.update(
                {
                    "pair_type": "clone",
                    "syntactic_type": 1,
                    "similarity_line": 1.0,
                    "similarity_token": 1.0,
                }
            )
            conflicting_positive = pair_row()
            write_export(exports / "positive.csv", [clean_positive, conflicting_positive])
            write_export(
                exports / "false.csv", [pair_row(reverse=True, pair_type="false")]
            )
            compiled = compile_exports(
                bce_dir=bce,
                data_root=root / "data",
                exports={
                    "positive": exports / "positive.csv",
                    "known_false_positive": exports / "false.csv",
                },
                compile_scope={"fixture": "content-conflict"},
            )

            for dedupe in ("exact-unordered-fragment-pair", "none"):
                directory, manifest, _ = create_selection(
                    compiled,
                    data_root=root / "data",
                    pair_set="known-false-positive",
                    mode="census",
                    dedupe=dedupe,
                )
                self.assertEqual(manifest["counts"]["selected_frames"], 0)
                self.assertEqual(
                    manifest["counts"]["content_label_conflict_excluded_frames"], 1
                )
                self.assertEqual(
                    manifest["request"]["eligibility"]["content_label_conflicts"],
                    "excluded",
                )
                exclusions = [
                    json.loads(line)
                    for line in (directory / "exclusions.jsonl").read_text().splitlines()
                ]
                self.assertEqual(
                    {item["reason"] for item in exclusions},
                    {"positive_negative_content_label_conflict"},
                )
                conflict = json.loads(
                    (directory / "label-conflicts.jsonl").read_text().splitlines()[0]
                )
                self.assertEqual(
                    conflict["reason"],
                    "positive_and_known_false_positive_rows_share_an_"
                    "unordered_fragment_content_pair",
                )
                self.assertEqual(
                    conflict["disposition"], "excluded_from_scored_selections"
                )

            for dedupe in ("exact-unordered-fragment-pair", "none"):
                type1_dir, type1, _ = create_selection(
                    compiled,
                    data_root=root / "data",
                    pair_set="type1",
                    mode="sample",
                    sample_size=1,
                    seed=0,
                    dedupe=dedupe,
                )
                self.assertEqual(type1["counts"]["selected_frames"], 1)
                self.assertEqual(
                    type1["counts"]["content_label_conflict_excluded_frames"], 1
                )
                self.assertEqual(
                    len((type1_dir / "frames.jsonl").read_text().splitlines()), 1
                )
                type1_exclusions = [
                    json.loads(line)
                    for line in (type1_dir / "exclusions.jsonl").read_text().splitlines()
                ]
                self.assertEqual(
                    {item["reason"] for item in type1_exclusions},
                    {"positive_negative_content_label_conflict"},
                )

    def test_pair_sets_and_sample_identity_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = self.compile_fixture(root)
            type1_dir, type1, _ = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="type1",
                mode="sample",
                sample_size=1,
                seed=17,
            )
            type2_dir, type2, _ = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="type2",
                mode="census",
            )
            type3_dir, type3, _ = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="type3",
                mode="census",
            )
            negative_dir, negative, _ = create_selection(
                compiled,
                data_root=root / "data",
                pair_set="known-false-positive",
                mode="census",
            )

            self.assertEqual(
                len({type1_dir.name, type2_dir.name, type3_dir.name, negative_dir.name}),
                4,
            )
            self.assertEqual(type1["request"]["sample"]["seed"], 17)
            self.assertEqual(type2["counts"]["selected_frames"], 1)
            self.assertEqual(type3["counts"]["selected_frames"], 1)
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
                dedupe="none",
            )
            self.assertEqual(manifest["counts"]["selected_frames"], 2)
            self.assertEqual(
                manifest["counts"]["reverse_direction_excluded_catalog_rows"], 0
            )

    def test_type3_sample_is_stratified_reproducible_and_compact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = self.compile_type3_fixture(root)
            first_dir, first, _ = create_selection(
                compiled,
                data_root=root / "publication-one",
                pair_set="type3",
                mode="sample",
                sample_size=4,
                seed=73,
            )
            second_dir, second, _ = create_selection(
                compiled,
                data_root=root / "publication-two",
                pair_set="type3",
                mode="sample",
                sample_size=4,
                seed=73,
            )

            self.assertEqual(first["selection_id"], second["selection_id"])
            self.assertEqual(
                (first_dir / "frames.jsonl").read_bytes(),
                (second_dir / "frames.jsonl").read_bytes(),
            )
            self.assertEqual(first["counts"]["eligible_frames"], 5)
            self.assertEqual(first["counts"]["selected_frames"], 4)
            self.assertEqual(first["counts"]["sample_excluded_frames"], 1)
            self.assertEqual(
                {name: values["selected_frames"] for name, values in first["strata"].items()},
                {"very_strong": 1, "strong": 1, "moderate": 1, "weak": 1},
            )
            self.assertTrue(
                all(values["allocated_frames"] > 0 for values in first["strata"].values())
            )
            exclusions = [
                json.loads(line)
                for line in (first_dir / "exclusions.jsonl").read_text().splitlines()
            ]
            self.assertEqual(
                {item["reason"] for item in exclusions},
                {"positive_negative_content_label_conflict"},
            )
            self.assertEqual(
                first["counts"]["content_label_conflict_excluded_frames"], 1
            )

    def test_type3_sample_smaller_than_the_strata_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = self.compile_type3_fixture(root)
            with self.assertRaisesRegex(ValueError, "at least 4"):
                create_selection(
                    compiled,
                    data_root=root / "small",
                    pair_set="type3",
                    mode="sample",
                    sample_size=3,
                )

    def test_type3_allocation_rejects_empty_strata_and_redistributes_caps(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty: weak"):
            _equal_type3_allocation(
                {"very_strong": 2, "strong": 2, "moderate": 2, "weak": 0}, 4
            )
        self.assertEqual(
            _equal_type3_allocation(
                {"very_strong": 1, "strong": 2, "moderate": 5, "weak": 5}, 8
            ),
            {"very_strong": 1, "strong": 2, "moderate": 3, "weak": 2},
        )


if __name__ == "__main__":
    unittest.main()
