from __future__ import annotations

import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from bigMoveBench.adapter import validate_srcdiff_semantics
from bigMoveBench.catalog import compile_exports
from bigMoveBench.contracts import SemanticStatus
from bigMoveBench.plan import SerialPlanRunner, load_plan, publish_plan
from bigMoveBench.selection import create_selection
from bigMoveBench.synthetic import (
    STABLE_WRAPPER_VERSION,
    SYNTHETIC_DESTINATION_PATH,
    SYNTHETIC_SOURCE_PATH,
)
from bigMoveBench.tests import test_catalog, test_snapshot


REPO_ROOT = Path(__file__).resolve().parents[2]


class NormalizedPlanTests(unittest.TestCase):
    def publish_fixture(self, root: Path, pair_set: str = "type3"):
        _, compiled = test_snapshot.BigCloneBenchSnapshotTests().compile_fixture(root)
        selection_directory, selection, _ = create_selection(
            compiled,
            data_root=root / "data",
            pair_set=pair_set,
            mode="census",
            role="tuning" if pair_set == "type3" else "evaluation",
        )
        plan, disposition = publish_plan(
            data_root=root / "data", selection=selection_directory
        )
        return compiled, selection, plan, disposition

    def publish_two_case_fixture(self, root: Path):
        fixture = test_catalog.BigCloneBenchCompiledDatasetTests()
        bce = fixture.create_bce(root)
        first = test_catalog.pair_row()
        first.update(
            {"pair_type": "type-3", "syntactic_type": 3}
        )
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
            compile_scope={"fixture": "normalized-plan-two-cases"},
        )
        selection_directory, selection, _ = create_selection(
            compiled,
            data_root=root / "data",
            pair_set="type3",
            mode="census",
            role="tuning",
        )
        plan, disposition = publish_plan(
            data_root=root / "data", selection=selection_directory
        )
        return compiled, selection, plan, disposition

    def test_publishes_normalized_immutable_plan_and_reuses_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled, selection, plan, disposition = self.publish_fixture(root)

            self.assertEqual(disposition, "created")
            self.assertEqual(
                plan.manifest["counts"],
                {"cases": 1, "case_rows": 1, "generated_objects": 4},
            )
            self.assertEqual(
                plan.manifest["compiled_dataset"]["dataset_id"],
                compiled.dataset_id,
            )
            self.assertEqual(
                plan.manifest["selection"]["selection_id"],
                selection["selection_id"],
            )
            self.assertEqual(plan.manifest["wrapper_version"], STABLE_WRAPPER_VERSION)

            database = plan.directory / "plan.sqlite"
            with sqlite3.connect(database) as connection:
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

            reused, reused_disposition = publish_plan(
                data_root=root / "data",
                selection=selection["selection_id"],
            )
            self.assertEqual(reused_disposition, "reused")
            self.assertEqual(reused.plan_id, plan.plan_id)
            self.assertEqual(reused.directory, plan.directory)
            load_plan(root / "data", plan.plan_id, verification="full")

    def test_full_verification_rejects_corrupted_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, plan, _ = self.publish_fixture(root)
            with sqlite3.connect(plan.directory / "plan.sqlite") as connection:
                relative = connection.execute(
                    "SELECT object_path FROM generated_objects "
                    "ORDER BY object_id LIMIT 1"
                ).fetchone()[0]
            object_path = root / "data" / relative
            object_path.chmod(0o644)
            object_path.write_text("corrupt\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "plan object is invalid"):
                load_plan(root / "data", plan.plan_id, verification="full")

    def test_serial_runner_reuses_one_four_file_scratch_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled, selection, plan, _ = self.publish_two_case_fixture(root)
            self.assertEqual(plan.manifest["counts"]["cases"], 2)
            self.assertEqual(plan.manifest["counts"]["generated_objects"], 6)
            observed_roots: list[Path] = []
            observed_strata: list[str] = []
            observed_scratch: Path | None = None

            with SerialPlanRunner(plan, scratch_root=root / "scratch") as runner:
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
            _, _, plan, _ = self.publish_fixture(root, "type1")
            with self.assertRaisesRegex(RuntimeError, "context manager"):
                next(SerialPlanRunner(plan).cases())

    def test_serial_archive_passes_the_srcdiff_semantic_gate(self) -> None:
        srcdiff = REPO_ROOT.parent / "srcDiff" / "build" / "bin" / "srcdiff"
        if not srcdiff.is_file():
            discovered = shutil.which("srcdiff")
            if discovered is None:
                self.skipTest("srcdiff executable is unavailable")
            srcdiff = Path(discovered)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, plan, _ = self.publish_fixture(root, "type3")
            output = root / "srcdiff.xml"
            with SerialPlanRunner(plan) as runner:
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
                _, _, plan, _ = self.publish_fixture(root, pair_set)
                with SerialPlanRunner(plan) as runner:
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
