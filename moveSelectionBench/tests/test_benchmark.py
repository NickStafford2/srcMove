from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from moveSelectionBench.benchmark import (
    CatalogError,
    evaluate_results,
    load_catalog,
    normalize_text,
    run_benchmark,
    summarize,
)


FIXTURE_XML = REPO_ROOT / "tests" / "fixtures" / "benchmark" / "input.srcdiff.xml"


def move(from_text: str, to_text: str, kind: str = "exact") -> dict[str, object]:
    return {
        "move_id": "m1",
        "match_kind": kind,
        "from_raw_texts": [from_text],
        "to_raw_texts": [to_text],
        "from_xpaths": ["/from"],
        "to_xpaths": ["/to"],
    }


def write_fake_srcmove(
    path: Path,
    moves: list[dict[str, object]],
    *,
    results_only_moves: list[dict[str, object]] | None = None,
) -> Path:
    encoded = repr(
        {
            "move_count": len(moves),
            "moves": moves,
            "candidates_total": 2,
            "groups_total": 1,
        }
    )
    results_only_encoded = repr(
        {
            "move_count": len(
                results_only_moves if results_only_moves is not None else moves
            ),
            "moves": results_only_moves if results_only_moves is not None else moves,
            "candidates_total": 2,
            "groups_total": 1,
        }
    )
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import shutil, sys\n"
        "from pathlib import Path\n"
        f"results_value = {encoded}\n"
        f"results_only_value = {results_only_encoded}\n"
        "results_only = '--results-only' in sys.argv\n"
        "if not results_only:\n"
        "    shutil.copyfile(sys.argv[1], sys.argv[2])\n"
        "results = Path(sys.argv[sys.argv.index('--results') + 1])\n"
        "value = results_only_value if results_only else results_value\n"
        "results.write_text(__import__('json').dumps(value))\n"
        "print('profile.content_groups.type3_pairs_considered=7', file=sys.stderr)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


class MoveSelectionBenchmarkTests(unittest.TestCase):
    def test_catalog_is_valid_and_contains_the_targeted_dimensions(self) -> None:
        cases = load_catalog(REPO_ROOT / "moveSelectionBench" / "catalog.json")
        self.assertGreaterEqual(len(cases), 15)
        self.assertEqual(
            {case["category"] for case in cases},
            {
                "same_side_nesting",
                "cross_type_competition",
                "common_ownership",
                "hierarchical_coherence",
                "ambiguity_and_granularity",
                "mixed_polarity",
                "deep_nesting",
                "cross_file",
                "one_sided_overlap",
            },
        )
        indexed = {case["id"]: case for case in cases}
        self.assertEqual({case["status"] for case in cases}, {"contract"})
        self.assertEqual(
            indexed["cross_file_nonlocal_move"]["input_shape"], "archive"
        )
        self.assertTrue(
            indexed["equal_score_deterministic"]["verify_results_only_equivalence"]
        )

    def test_semantic_evaluation_normalizes_whitespace_and_checks_forbidden(self) -> None:
        case = {
            "required": [{"from": "whole old", "to": "whole new", "match_kinds": ["type3"]}],
            "forbidden": [{"from": "small();", "to": "small();"}],
        }
        passing = evaluate_results(
            case,
            {"moves": [move(" whole  old ", "whole\nnew", "type3")]},
        )
        self.assertEqual(passing["status"], "pass")
        self.assertEqual(normalize_text(" a\n  b "), "a b")

        failing = evaluate_results(
            case,
            {"moves": [move("small();", "small();")]},
        )
        self.assertEqual(failing["status"], "semantic_miss")
        self.assertEqual(failing["required_found"], 0)
        self.assertEqual(failing["forbidden_found"], 1)

    def test_malformed_result_move_is_a_validation_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid shape"):
            evaluate_results(
                {"required": [], "forbidden": []},
                {"moves": [{"match_kind": "exact"}]},
            )

    def test_summary_reports_baseline_transitions(self) -> None:
        summary = summarize(
            [
                {"variant": "base", "case_id": "a", "semantic_status": "semantic_miss"},
                {"variant": "new", "case_id": "a", "semantic_status": "pass"},
                {"variant": "base", "case_id": "b", "semantic_status": "pass"},
                {"variant": "new", "case_id": "b", "semantic_status": "semantic_miss"},
            ],
            "base",
        )
        self.assertEqual(
            summary["transitions_from_baseline"]["new"],
            {"pass_to_semantic_miss": 1, "semantic_miss_to_pass": 1},
        )

    def test_semantic_miss_does_not_become_a_hard_run_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture = root / "input.xml"
            fixture.write_bytes(FIXTURE_XML.read_bytes())
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "cases": [
                            {
                                "id": "one",
                                "status": "hypothesis",
                                "input": "input.xml",
                                "category": "fixture",
                                "rationale": "exercise runner",
                                "required": [{"from": "wanted", "to": "wanted"}],
                                "forbidden": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            baseline = write_fake_srcmove(root / "baseline", [])
            candidate = write_fake_srcmove(root / "candidate", [move("wanted", "wanted")])
            run_dir, summary = run_benchmark(
                catalog_path=catalog,
                variants={"baseline": baseline, "candidate": candidate},
                output_root=root / "results",
                baseline="baseline",
                timeout_seconds=3.0,
                run_id="comparison",
            )
            self.assertEqual(summary["hard_failures"], 0)
            self.assertEqual(summary["contract_semantic_misses"], 0)
            self.assertEqual(summary["variants"]["baseline"]["semantic_miss"], 1)
            self.assertEqual(summary["variants"]["candidate"]["pass"], 1)
            self.assertEqual(
                summary["transitions_from_baseline"]["candidate"],
                {"semantic_miss_to_pass": 1},
            )
            outcomes = json.loads((run_dir / "outcomes.json").read_text())["outcomes"]
            self.assertEqual(outcomes[0]["profile"]["content_groups.type3_pairs_considered"], 7)

    def test_catalog_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            catalog = Path(temporary_directory) / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "cases": [
                            {
                                "id": "unsafe",
                                "status": "contract",
                                "input": "../input.xml",
                                "required": [],
                                "forbidden": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CatalogError, "unsafe"):
                load_catalog(catalog)

    def test_results_only_difference_is_a_semantic_miss(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixture = root / "input.xml"
            fixture.write_bytes(FIXTURE_XML.read_bytes())
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "cases": [
                            {
                                "id": "equivalence",
                                "status": "contract",
                                "input": "input.xml",
                                "verify_results_only_equivalence": True,
                                "required": [{"from": "wanted", "to": "wanted"}],
                                "forbidden": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            tool = write_fake_srcmove(
                root / "tool",
                [move("wanted", "wanted")],
                results_only_moves=[move("other", "other")],
            )
            run_dir, summary = run_benchmark(
                catalog_path=catalog,
                variants={"current": tool},
                output_root=root / "results",
                baseline="current",
                timeout_seconds=3.0,
                run_id="equivalence",
            )
            self.assertEqual(summary["hard_failures"], 0)
            self.assertEqual(summary["variants"]["current"]["semantic_miss"], 1)
            outcome = json.loads((run_dir / "outcomes.json").read_text())["outcomes"][0]
            self.assertFalse(outcome["results_only_equivalent"])
            self.assertEqual(summary["contract_semantic_misses"], 1)


if __name__ == "__main__":
    unittest.main()
