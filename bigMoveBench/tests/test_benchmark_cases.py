from __future__ import annotations

import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from bigMoveBench.adapter import _type3_frame_strength, validate_srcdiff_semantics
from bigMoveBench.benchmark_cases import (
    SerialBenchmarkCaseRunner,
    load_benchmark_cases,
    publish_benchmark_cases,
)
from bigMoveBench.catalog import compile_exports
from bigMoveBench.contracts import SemanticStatus
from bigMoveBench.selection import create_selection
from bigMoveBench.synthetic import (
    STABLE_WRAPPER_VERSION,
    SYNTHETIC_DESTINATION_PATH,
    SYNTHETIC_SOURCE_PATH,
)
from bigMoveBench.tests import test_catalog


REPO_ROOT = Path(__file__).resolve().parents[2]


def compile_fixture(root: Path):
    fixture = test_catalog.BigCloneBenchCompiledDatasetTests()
    bce = fixture.create_bce(root)
    exports = root / "exports"
    exports.mkdir()
    type_one = test_catalog.pair_row()
    type_two = test_catalog.pair_row()
    type_two.update({"syntactic_type": 2, "pair_type": "type-2"})
    type_three = test_catalog.pair_row()
    type_three.update({"syntactic_type": 3, "pair_type": "type-3"})
    test_catalog.write_export(
        exports / "positive.csv", [type_one, type_two, type_three]
    )
    false_positive = test_catalog.distinct_false_positive_row(bce)
    false_positive["syntactic_type"] = 3
    test_catalog.write_export(exports / "false.csv", [false_positive])
    compiled = compile_exports(
        bce_dir=bce,
        data_root=root / "data",
        exports={
            "positive": exports / "positive.csv",
            "known_false_positive": exports / "false.csv",
        },
        compile_scope={"fixture": "normalized-benchmark-cases"},
    )
    return bce, compiled


class NormalizedBenchmarkCasesTests(unittest.TestCase):
    def test_type_three_frame_strength_is_conservative_across_rows(self) -> None:
        strength, stratum = _type3_frame_strength(
            [
                {"similarity": {"line": 0.96, "token": 0.94}},
                {"similarity": {"line": 0.89, "token": 0.91}},
            ]
        )
        self.assertEqual(strength, 0.89)
        self.assertEqual(stratum, "strong")

    def publish_fixture(self, root: Path, pair_set: str = "type3"):
        _, compiled = compile_fixture(root)
        selection_directory, selection, _ = create_selection(
            compiled,
            data_root=root / "data",
            pair_set=pair_set,
            mode="census",
        )
        benchmark_cases, disposition = publish_benchmark_cases(
            data_root=root / "data", selection=selection_directory
        )
        return compiled, selection, benchmark_cases, disposition

    def publish_two_case_fixture(self, root: Path):
        fixture = test_catalog.BigCloneBenchCompiledDatasetTests()
        bce = fixture.create_bce(root)
        first = test_catalog.pair_row()
        first.update({"pair_type": "type-3", "syntactic_type": 3})
        second = test_catalog.distinct_false_positive_row(bce)
        second["pair_type"] = "type-3"
        exports = root / "exports"
        exports.mkdir()
        test_catalog.write_export(exports / "positive.csv", [first, second])
        test_catalog.write_export(exports / "false.csv", [])
        compiled = compile_exports(
            bce_dir=bce,
            data_root=root / "data",
            exports={
                "positive": exports / "positive.csv",
                "known_false_positive": exports / "false.csv",
            },
            compile_scope={"fixture": "normalized-benchmark-cases-two-cases"},
        )
        selection_directory, selection, _ = create_selection(
            compiled,
            data_root=root / "data",
            pair_set="type3",
            mode="census",
        )
        benchmark_cases, disposition = publish_benchmark_cases(
            data_root=root / "data", selection=selection_directory
        )
        return compiled, selection, benchmark_cases, disposition

    def test_publishes_normalized_immutable_cases_and_reuses_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled, selection, benchmark_cases, disposition = self.publish_fixture(
                root
            )

            self.assertEqual(disposition, "created")
            self.assertEqual(
                benchmark_cases.manifest["counts"],
                {"cases": 1, "case_rows": 1, "generated_objects": 4},
            )
            self.assertEqual(
                benchmark_cases.manifest["compiled_dataset"]["dataset_id"],
                compiled.dataset_id,
            )
            self.assertEqual(
                benchmark_cases.manifest["selection"]["selection_id"],
                selection["selection_id"],
            )
            self.assertEqual(
                benchmark_cases.manifest["wrapper_version"], STABLE_WRAPPER_VERSION
            )
            self.assertEqual(
                benchmark_cases.manifest["artifacts"]["benchmark_cases"]["path"],
                "benchmark_cases.sqlite",
            )

            database = benchmark_cases.directory / "benchmark_cases.sqlite"
            with closing(sqlite3.connect(database)) as connection:
                case_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(cases)")
                }
                self.assertNotIn("fragment_text", case_columns)
                self.assertNotIn("selection_frame", case_columns)
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(DISTINCT object_path) FROM generated_objects"
                    ).fetchone()[0],
                    4,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT syntactic_type FROM case_rows"
                    ).fetchone()[0],
                    3,
                )

            reused, reused_disposition = publish_benchmark_cases(
                data_root=root / "data",
                selection=selection["selection_id"],
            )
            self.assertEqual(reused_disposition, "reused")
            self.assertEqual(
                reused.benchmark_cases_id, benchmark_cases.benchmark_cases_id
            )
            self.assertEqual(reused.directory, benchmark_cases.directory)
            load_benchmark_cases(
                root / "data",
                benchmark_cases.benchmark_cases_id,
                verification="full",
            )

    def test_full_verification_rejects_corrupted_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, benchmark_cases, _ = self.publish_fixture(root)
            with closing(
                sqlite3.connect(
                    benchmark_cases.directory / "benchmark_cases.sqlite"
                )
            ) as connection:
                relative = connection.execute(
                    "SELECT object_path FROM generated_objects "
                    "ORDER BY object_id LIMIT 1"
                ).fetchone()[0]
            object_path = root / "data" / relative
            object_path.chmod(0o644)
            object_path.write_text("corrupt\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError, "benchmark cases object is invalid"
            ):
                load_benchmark_cases(
                    root / "data",
                    benchmark_cases.benchmark_cases_id,
                    verification="full",
                )

    def test_serial_runner_reuses_one_four_file_scratch_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled, selection, benchmark_cases, _ = (
                self.publish_two_case_fixture(root)
            )
            self.assertEqual(benchmark_cases.manifest["counts"]["cases"], 2)
            self.assertEqual(
                benchmark_cases.manifest["counts"]["generated_objects"], 6
            )
            observed_roots: list[Path] = []
            observed_strata: list[str] = []
            observed_scratch: Path | None = None

            with SerialBenchmarkCaseRunner(
                benchmark_cases, scratch_root=root / "scratch"
            ) as runner:
                self.assertIsNotNone(runner._root)
                observed_scratch = runner._root

                def inspect(case) -> None:
                    observed_roots.append(case.original.parent)
                    self.assertEqual(case.original.parent, case.modified.parent)
                    expected_files = {
                        case.original / SYNTHETIC_SOURCE_PATH,
                        case.original / SYNTHETIC_DESTINATION_PATH,
                        case.modified / SYNTHETIC_SOURCE_PATH,
                        case.modified / SYNTHETIC_DESTINATION_PATH,
                    }
                    self.assertTrue(all(path.is_file() for path in expected_files))
                    self.assertEqual(
                        set(case.original.parent.rglob("*.java")), expected_files
                    )
                    self.assertEqual(case.metadata["syntactic_types"], [3])
                    observed_strata.append(case.metadata["type3_strength_stratum"])
                    self.assertEqual(
                        case.metadata["compiled_dataset_id"], compiled.dataset_id
                    )
                    self.assertEqual(
                        case.metadata["selection_id"], selection["selection_id"]
                    )
                    expected = case.metadata["expected"]
                    self.assertIn(
                        expected["from_generated_text"].strip(),
                        (case.original / SYNTHETIC_SOURCE_PATH).read_text(),
                    )
                    self.assertIn(
                        expected["to_generated_text"].strip(),
                        (case.modified / SYNTHETIC_DESTINATION_PATH).read_text(),
                    )

                self.assertEqual(runner.run(inspect), 2)

            self.assertEqual(observed_roots, [observed_scratch, observed_scratch])
            self.assertEqual(observed_strata, ["very_strong", "moderate"])
            assert observed_scratch is not None
            self.assertFalse(observed_scratch.exists())

    def test_serial_runner_requires_context_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, benchmark_cases, _ = self.publish_fixture(root, "type1")
            with self.assertRaisesRegex(RuntimeError, "context manager"):
                next(SerialBenchmarkCaseRunner(benchmark_cases).cases())

    def test_serial_archive_passes_the_srcdiff_semantic_gate(self) -> None:
        srcdiff = REPO_ROOT.parent / "srcDiff" / "build" / "bin" / "srcdiff"
        if not srcdiff.is_file():
            discovered = shutil.which("srcdiff")
            if discovered is None:
                self.skipTest("srcdiff executable is unavailable")
            srcdiff = Path(discovered)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, benchmark_cases, _ = self.publish_fixture(root, "type3")
            output = root / "srcdiff.xml"
            with SerialBenchmarkCaseRunner(benchmark_cases) as runner:
                case = next(runner.cases())
                try:
                    result = subprocess.run(
                        [
                            str(srcdiff),
                            "--position",
                            "--archive",
                            str(case.original),
                            str(case.modified),
                            "-o",
                            str(output),
                        ],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                except OSError as error:
                    self.skipTest(f"srcdiff executable cannot run here: {error}")
                self.assertEqual(result.returncode, 0, result.stderr)
                semantic = validate_srcdiff_semantics(case, output)
                self.assertEqual(semantic.status, SemanticStatus.ELIGIBLE)

    def test_all_pair_sets_preserve_case_kind_and_expected_count(self) -> None:
        declarations = (
            ("type1", "positive", 1, 1),
            ("type2", "positive", 2, 1),
            ("type3", "positive", 3, 1),
            ("known-false-positive", "known_false_positive", 3, 0),
        )
        for pair_set, case_kind, syntactic_type, move_count in declarations:
            with (
                self.subTest(pair_set=pair_set),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                _, _, benchmark_cases, _ = self.publish_fixture(root, pair_set)
                with SerialBenchmarkCaseRunner(benchmark_cases) as runner:
                    cases = runner.cases()
                    case = next(cases)
                    self.assertEqual(case.metadata["case_kind"], case_kind)
                    self.assertEqual(case.metadata["syntactic_type"], syntactic_type)
                    self.assertEqual(
                        case.metadata["expected"]["move_count"], move_count
                    )
                    with self.assertRaises(StopIteration):
                        next(cases)


if __name__ == "__main__":
    unittest.main()
