"""Preserved independent catalog validation and oracle contracts."""
import json
import tempfile
import unittest
from pathlib import Path
from tests.support.selection_catalog import CatalogError, evaluate_results, load_catalog, normalize_text
REPO_ROOT = Path(__file__).resolve().parents[2]

def move(from_text: str, to_text: str, kind: str = "type1") -> dict[str, object]:
    return {
        "move_id": "m1",
        "content_relationship": kind,
        "from_raw_texts": [from_text],
        "to_raw_texts": [to_text],
        "from_xpaths": ["/from"],
        "to_xpaths": ["/to"],
    }

class SelectionCatalogTests(unittest.TestCase):
    def test_catalog_is_valid_and_contains_the_targeted_dimensions(self) -> None:
            cases = load_catalog(REPO_ROOT / "tests/fixtures/selection/catalog.json")
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
                    "stationary_correspondence",
                    "same_parent_reorder",
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
                "required": [{"from": "whole old", "to": "whole new", "content_relationships": ["type3"]}],
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
                    {"moves": [{"content_relationship": "type1"}]},
                )

    def test_catalog_rejects_parent_traversal(self) -> None:
            with tempfile.TemporaryDirectory() as temporary_directory:
                catalog = Path(temporary_directory) / "catalog.json"
                catalog.write_text(
                    json.dumps(
                        {
                            "schema_version": 3,
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
