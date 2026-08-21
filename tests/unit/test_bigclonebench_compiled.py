from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


from benchmarks.bigclonebench.compile import (
    _false_positive_query,
    _positive_query,
    cached_or_export_h2,
)
from benchmarks.bigclonebench.compiled import (
    compile_exports,
    find_reusable_compiled_dataset,
    load_compiled_dataset,
    verify_upstream_sources,
)


FIELDS = (
    "functionality_id",
    "function_id_one",
    "typeone",
    "nameone",
    "startlineone",
    "endlineone",
    "projectone",
    "tokensone",
    "internalone",
    "function_id_two",
    "typetwo",
    "nametwo",
    "startlinetwo",
    "endlinetwo",
    "projecttwo",
    "tokenstwo",
    "internaltwo",
    "pair_type",
    "syntactic_type",
    "similarity_line",
    "similarity_token",
    "min_size",
    "max_size",
    "min_pretty_size",
    "max_pretty_size",
    "min_tokens",
    "max_tokens",
    "min_judges",
    "min_confidence",
    "pair_internal",
)


def write_export(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def pair_row(*, reverse: bool = False, pair_type: str = "positive") -> dict[str, object]:
    functions = [
        {
            "id": 11,
            "type": "default",
            "name": "A.java",
            "project": "alpha",
            "tokens": 60,
        },
        {
            "id": 22,
            "type": "sample",
            "name": "B.java",
            "project": "beta",
            "tokens": 70,
        },
    ]
    if reverse:
        functions.reverse()
    one, two = functions
    return {
        "functionality_id": 7,
        "function_id_one": one["id"],
        "typeone": one["type"],
        "nameone": one["name"],
        "startlineone": 2,
        "endlineone": 4,
        "projectone": one["project"],
        "tokensone": one["tokens"],
        "internalone": "FALSE",
        "function_id_two": two["id"],
        "typetwo": two["type"],
        "nametwo": two["name"],
        "startlinetwo": 2,
        "endlinetwo": 4,
        "projecttwo": two["project"],
        "tokenstwo": two["tokens"],
        "internaltwo": "FALSE",
        "pair_type": "sample-tagged" if pair_type == "false" else "clone",
        "syntactic_type": 3 if pair_type == "false" else 1,
        "similarity_line": 0.5 if pair_type == "false" else 1.0,
        "similarity_token": 0.6 if pair_type == "false" else 1.0,
        "min_size": "" if pair_type == "false" else 3,
        "max_size": "" if pair_type == "false" else 3,
        "min_pretty_size": "" if pair_type == "false" else 3,
        "max_pretty_size": "" if pair_type == "false" else 3,
        "min_tokens": min(one["tokens"], two["tokens"]),
        "max_tokens": max(one["tokens"], two["tokens"]),
        "min_judges": 1,
        "min_confidence": 1,
        "pair_internal": "FALSE",
    }


class BigCloneBenchCompiledDatasetTests(unittest.TestCase):
    def create_bce(self, root: Path) -> Path:
        bce = root / "BigCloneEval"
        (bce / "bigclonebenchdb").mkdir(parents=True)
        (bce / "bigclonebenchdb" / "bcb.h2.db").write_bytes(b"fixture-db")
        (bce / "libs").mkdir()
        (bce / "libs" / "h2-1.3.176.jar").write_bytes(b"fixture-h2")
        reduced = bce / "ijadataset" / "bcb_reduced" / "7"
        (reduced / "default").mkdir(parents=True)
        (reduced / "sample").mkdir()
        (reduced / "default" / "A.java").write_text(
            "class A {\n  void alpha() {\n    callA();\n  }\n}\n"
        )
        (reduced / "sample" / "B.java").write_text(
            "class B {\n  void beta() {\n    callB();\n  }\n}\n"
        )
        return bce

    def compile_fixture(
        self,
        root: Path,
        *,
        reverse_exports: bool = False,
        distinct_rows: bool = False,
        identical_fragments: bool = False,
        progress_callback=None,
    ):
        bce = self.create_bce(root)
        if identical_fragments:
            (bce / "ijadataset/bcb_reduced/7/sample/B.java").write_text(
                "class B {\n  void alpha() {\n    callA();\n  }\n}\n"
            )
        exports = root / "exports"
        exports.mkdir()
        positive_rows = [pair_row(), pair_row()]
        if distinct_rows:
            positive_rows[1]["similarity_line"] = 0.9
        if reverse_exports:
            positive_rows.reverse()
        write_export(exports / "positive.csv", positive_rows)
        write_export(
            exports / "false.csv",
            [pair_row(reverse=True, pair_type="false")],
        )
        compiled = compile_exports(
            bce_dir=bce,
            data_root=root / "data",
            exports={
                "positive": exports / "positive.csv",
                "known_false_positive": exports / "false.csv",
            },
            compile_scope={"fixture": True, "external_only": True},
            java={"version": "fixture"},
            progress_callback=progress_callback,
        )
        return bce, compiled

    def test_compile_deduplicates_fragments_and_preserves_row_multiplicity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bce, compiled = self.compile_fixture(root)

            counts = compiled.manifest["counts"]
            self.assertEqual(counts["positive_source_rows"], 2)
            self.assertEqual(counts["known_false_positive_source_rows"], 1)
            self.assertEqual(counts["catalog_pair_rows"], 2)
            self.assertEqual(counts["duplicate_source_rows"], 1)
            self.assertEqual(counts["unique_fragments"], 2)
            self.assertEqual(counts["unique_ordered_pairs"], 2)
            self.assertEqual(counts["unique_unordered_pairs"], 1)
            self.assertEqual(counts["positive_negative_label_conflicts"], 1)

            catalog = compiled.directory / "catalog.sqlite"
            with closing(sqlite3.connect(catalog)) as connection:
                pairs = connection.execute(
                    "SELECT pair_kind, source_row_multiplicity, canonical_direction "
                    "FROM pair_rows ORDER BY pair_kind"
                ).fetchall()
            self.assertEqual([row[:2] for row in pairs], [
                ("known_false_positive", 1),
                ("positive", 2),
            ])
            self.assertEqual({row[2] for row in pairs}, {"forward", "reverse"})
            self.assertEqual(
                verify_upstream_sources(compiled, bce_dir=bce)["status"],
                "metadata_match",
            )
            self.assertEqual(
                verify_upstream_sources(
                    compiled, bce_dir=bce, verification="full"
                )["status"],
                "verified",
            )
            reused = find_reusable_compiled_dataset(
                data_root=root / "data",
                bce_dir=bce,
                compile_scope={"fixture": True, "external_only": True},
            )
            self.assertIsNotNone(reused)
            self.assertEqual(reused.dataset_id, compiled.dataset_id)

            source = (
                bce
                / "ijadataset"
                / "bcb_reduced"
                / "7"
                / "default"
                / "A.java"
            )
            source.write_text(source.read_text() + "// changed\n")
            self.assertIsNone(
                find_reusable_compiled_dataset(
                    data_root=root / "data",
                    bce_dir=bce,
                    compile_scope={"fixture": True, "external_only": True},
                )
            )

    def test_full_validation_detects_fragment_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, compiled = self.compile_fixture(root)
            fragment = next((compiled.directory / "fragments").rglob("*.java"))
            fragment.write_text("tampered\n")

            load_compiled_dataset(compiled.directory, verification="catalog")
            with self.assertRaisesRegex(ValueError, "fragment checksum"):
                load_compiled_dataset(compiled.directory, verification="full")

    def test_distinct_functions_can_share_one_fragment_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            progress = []
            _, compiled = self.compile_fixture(
                Path(temporary),
                identical_fragments=True,
                progress_callback=lambda event, phase, completed, total, detail: progress.append(
                    (event, phase, completed, total, detail)
                ),
            )
            self.assertEqual(compiled.manifest["counts"]["unique_fragments"], 1)
            self.assertEqual(compiled.manifest["counts"]["extracted_functions"], 2)
            phases = [(event, phase) for event, phase, *_ in progress]
            self.assertIn(("start", "import"), phases)
            self.assertIn(("finish", "fragments"), phases)
            self.assertIn(("finish", "pairs"), phases)
            self.assertIn(("finish", "index"), phases)
            self.assertIn(("finish", "finalize"), phases)
            fragment_finish = next(
                item
                for item in progress
                if item[0:2] == ("finish", "fragments")
            )
            self.assertEqual(fragment_finish[2:4], (2, 2))
            self.assertEqual(fragment_finish[4], "1 unique fragments")

    def test_full_upstream_verification_accepts_identical_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bce, compiled = self.compile_fixture(root)
            copied = root / "copied-bce"
            shutil.copytree(bce, copied)

            self.assertEqual(
                verify_upstream_sources(
                    compiled, bce_dir=copied, verification="full"
                )["status"],
                "verified",
            )
            self.assertEqual(
                verify_upstream_sources(compiled, bce_dir=copied)["status"],
                "mismatch",
            )

    def test_reuse_stops_when_a_previously_missing_source_appears(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bce = self.create_bce(root)
            missing = bce / "ijadataset/bcb_reduced/7/sample/B.java"
            missing.unlink()
            exports = root / "exports"
            exports.mkdir()
            write_export(exports / "positive.csv", [pair_row()])
            write_export(exports / "false.csv", [])
            scope = {"fixture": "missing"}
            compiled = compile_exports(
                bce_dir=bce,
                data_root=root / "data",
                exports={
                    "positive": exports / "positive.csv",
                    "known_false_positive": exports / "false.csv",
                },
                compile_scope=scope,
            )
            self.assertEqual(compiled.manifest["counts"]["extraction_failures"], 1)
            missing.write_text("class B {}\n")
            self.assertIsNone(
                find_reusable_compiled_dataset(
                    data_root=root / "data", bce_dir=bce, compile_scope=scope
                )
            )

    def test_catalog_logical_inventory_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, compiled = self.compile_fixture(root)
            catalog = compiled.directory / "catalog.sqlite"
            with closing(sqlite3.connect(catalog)) as connection:
                connection.execute(
                    "UPDATE pair_rows SET source_row_multiplicity=3 "
                    "WHERE pair_kind='positive'"
                )
                connection.commit()
            manifest_path = compiled.directory / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["artifacts"]["catalog"]["sha256"] = hashlib.sha256(
                catalog.read_bytes()
            ).hexdigest()
            stat = catalog.stat()
            manifest["artifacts"]["catalog"]["size_bytes"] = stat.st_size
            manifest_path.write_text(json.dumps(manifest))

            with self.assertRaisesRegex(ValueError, "counts|logical inventory"):
                load_compiled_dataset(compiled.directory)

    def test_full_validation_rejects_extra_fragment_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, compiled = self.compile_fixture(root)
            (compiled.directory / "fragments" / "extra.bin").write_bytes(b"extra")
            with self.assertRaisesRegex(ValueError, "missing or extra"):
                load_compiled_dataset(compiled.directory, verification="full")

    def test_dataset_identity_is_independent_of_export_row_order(self) -> None:
        with (
            tempfile.TemporaryDirectory() as left_temporary,
            tempfile.TemporaryDirectory() as right_temporary,
        ):
            _, left = self.compile_fixture(Path(left_temporary), distinct_rows=True)
            _, right = self.compile_fixture(
                Path(right_temporary), reverse_exports=True, distinct_rows=True
            )
            self.assertEqual(left.dataset_id, right.dataset_id)

    def test_full_exports_skip_unneeded_global_ordering(self) -> None:
        self.assertNotIn("ORDER BY", _positive_query(None))
        self.assertNotIn("ORDER BY", _false_positive_query(None))
        self.assertIn("ORDER BY", _positive_query(10))
        self.assertIn("LIMIT 10", _false_positive_query(10))

    def test_checked_exports_survive_catalog_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bce = self.create_bce(root)
            data_root = root / "data"
            scope = {"fixture": True, "limit_per_kind": None}
            activity = []

            def fake_export(export_dir, *, bce_dir, limit_per_kind):
                self.assertEqual(bce_dir, bce)
                self.assertIsNone(limit_per_kind)
                export_dir.mkdir(parents=True, exist_ok=True)
                positive = export_dir / "positive.csv"
                false_positive = export_dir / "known_false_positive.csv"
                positive.write_text("positive\n")
                false_positive.write_text("false\n")
                return {
                    "positive": positive,
                    "known_false_positive": false_positive,
                }

            with patch(
                "benchmarks.bigclonebench.compile.export_h2",
                side_effect=fake_export,
            ) as export:
                first, cache, reused = cached_or_export_h2(
                    data_root=data_root,
                    bce_dir=bce,
                    compile_scope=scope,
                    limit_per_kind=None,
                    activity_callback=activity.append,
                )
                second, second_cache, second_reused = cached_or_export_h2(
                    data_root=data_root,
                    bce_dir=bce,
                    compile_scope=scope,
                    limit_per_kind=None,
                    activity_callback=activity.append,
                )

            self.assertFalse(reused)
            self.assertTrue(second_reused)
            self.assertEqual(cache, second_cache)
            self.assertEqual(first, second)
            self.assertEqual(export.call_count, 1)
            self.assertIn("querying H2 serially", activity)
            self.assertIn("checksumming positive export", activity)
            self.assertIn("verifying saved positive export", activity)


if __name__ == "__main__":
    unittest.main()
