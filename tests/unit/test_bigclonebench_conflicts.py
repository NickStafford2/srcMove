from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from benchmarks.bigclonebench.conflicts import build_report
from benchmarks.bigclonebench.compiled import compile_exports
from tests.unit import test_bigclonebench_compiled as compiled_fixtures


class BigCloneBenchConflictReportTests(unittest.TestCase):
    def test_report_explains_content_identity_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = compiled_fixtures.BigCloneBenchCompiledDatasetTests(
                methodName="test_full_exports_skip_unneeded_global_ordering"
            )
            bce = fixture.create_bce(root)
            exports = root / "exports"
            exports.mkdir()
            compiled_fixtures.write_export(
                exports / "positive.csv", [compiled_fixtures.pair_row()]
            )
            compiled_fixtures.write_export(
                exports / "false.csv",
                [compiled_fixtures.pair_row(reverse=True, pair_type="false")],
            )
            compiled = compile_exports(
                bce_dir=bce,
                data_root=root / "data",
                exports={
                    "positive": exports / "positive.csv",
                    "known_false_positive": exports / "false.csv",
                },
                compile_scope={"fixture": "conflict-report"},
            )

            report = build_report(
                SimpleNamespace(
                    dataset=compiled.directory,
                    data_root=root / "data",
                    limit=1,
                )
            )

            self.assertEqual(report["content_conflict_count"], 1)
            self.assertEqual(report["positive_catalog_rows"], 1)
            self.assertEqual(report["known_false_positive_catalog_rows"], 1)
            self.assertEqual(report["same_bigclonebench_function_pair_conflicts"], 1)
            self.assertEqual(report["positive_catalog_rows_by_syntactic_type"], {"1": 1})
            self.assertEqual(len(report["examples"]), 1)
            self.assertIn("content identities are excluded", report["cause"])


if __name__ == "__main__":
    unittest.main()
