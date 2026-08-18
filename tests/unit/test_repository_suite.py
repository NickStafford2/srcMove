from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.repositories.run import (
    CaseOutcome,
    load_suite_configuration,
    print_summary,
    select_cases,
    suite_exit_code,
)


def write_case(root: Path, name: str, *, revisions: bool = True) -> None:
    case_dir = root / name
    case_dir.mkdir(parents=True)
    value = {"github": f"https://example.invalid/{name}.git"}
    if revisions:
        value.update({"old_rev": "v1", "new_rev": "v2"})
    (case_dir / "info.json").write_text(json.dumps(value), encoding="utf-8")


def write_configuration(root: Path, cases: list[str]) -> Path:
    path = root / "suites.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "default_suite": "standard",
                "suites": {
                    "standard": {
                        "description": "fixture suite",
                        "cases": cases,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


class RepositorySuiteTests(unittest.TestCase):
    def test_selection_preserves_config_then_explicit_case_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for case in ("first", "second", "extra"):
                write_case(root, case)
            configuration = load_suite_configuration(
                write_configuration(root, ["first", "second"]),
                benchmark_root=root,
            )

            suite, cases = select_cases(
                configuration,
                None,
                ["extra"],
                ["second"],
                benchmark_root=root,
            )

            self.assertEqual(suite, "standard")
            self.assertEqual(cases, ("first", "extra"))

    def test_configuration_rejects_duplicates_unknown_and_unpinned_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_case(root, "valid")
            with self.assertRaisesRegex(ValueError, "duplicate cases"):
                load_suite_configuration(
                    write_configuration(root, ["valid", "valid"]),
                    benchmark_root=root,
                )

            with self.assertRaisesRegex(ValueError, "unknown.*missing"):
                load_suite_configuration(
                    write_configuration(root, ["missing"]), benchmark_root=root
                )

            write_case(root, "unpinned", revisions=False)
            with self.assertRaisesRegex(ValueError, "no configured revisions"):
                load_suite_configuration(
                    write_configuration(root, ["unpinned"]), benchmark_root=root
                )

    def test_summary_retains_completed_results_when_one_case_fails(self) -> None:
        completed = {
            "status": "completed",
            "srcdiff_attempt": {"elapsed_seconds": 12.4},
            "srcmove_attempt": {"elapsed_seconds": 1.8},
            "results": {"move_count": 37},
        }
        failed = {
            "status": "srcdiff_failed",
            "srcdiff_attempt": {"elapsed_seconds": 3.2},
        }
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            print_summary(
                "standard",
                "fixture-series",
                [
                    CaseOutcome("notepadpp", 0, completed),
                    CaseOutcome("broken", 1, failed),
                ],
                Path("/tmp/fixture-series/summary.csv"),
            )

        rendered = output.getvalue()
        self.assertIn("COMPLETED WITH FAILURES", rendered)
        self.assertIn("1 completed, 1 failed, 2 selected", rendered)
        self.assertIn("notepadpp", rendered)
        self.assertIn("12.4s", rendered)
        self.assertIn("37", rendered)
        self.assertIn("broken", rendered)
        self.assertIn("srcdiff_failed", rendered)
        self.assertIn("/tmp/fixture-series/summary.csv", rendered)
        self.assertEqual(
            suite_exit_code(
                [
                    CaseOutcome("notepadpp", 0, completed),
                    CaseOutcome("broken", 1, failed),
                ]
            ),
            1,
        )

    def test_checked_in_standard_suite_is_explicit_and_excludes_unsuitable_cases(self) -> None:
        configuration = load_suite_configuration()
        self.assertEqual(
            configuration.suites["standard"].cases,
            ("notepadpp", "sqlite", "srcMove"),
        )
        self.assertNotIn("wowy_advanced_analytics", configuration.suites["standard"].cases)
        self.assertNotIn("linux", configuration.suites["standard"].cases)


if __name__ == "__main__":
    unittest.main()
