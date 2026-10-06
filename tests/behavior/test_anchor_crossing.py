"""Displacement needs a shared mapped sibling, rather than function-wide order."""
from __future__ import annotations
from tests.support.execution import require_success, require_tool
import json
from pathlib import Path
import sys
from tests.support.execution import artifact_directory, run_logged
import unittest
from tests.support.readable_cases import case_xml
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from benchmarking.tooling import find_srcmove
TARGET_TEXT = 'int target = source + 17;'

class AnchorCrossingTests(unittest.TestCase):

    def evaluate(self, body: str) -> dict:
        binary = find_srcmove(REPO_ROOT, None)
        require_tool(binary)
        with artifact_directory(case_id=self.id()) as directory:
            root = Path(directory)
            fixture = root / 'input.xml'
            fixture.write_text(body)
            result = root / 'results.json'
            completed = run_logged([str(binary), str(fixture), '--results-only', '--results', str(result), '--diagnostics'], capture_output=True, text=True)
            require_success(completed)
            return json.loads(result.read_text())

    def target_moves(self, body: str) -> list[dict]:
        return [move for move in self.evaluate(body)['moves'] if TARGET_TEXT in move['from_raw_texts']]

    def test_call_is_a_shared_crossed_sibling(self):
        """Call is a shared crossed sibling."""
        self.assertEqual(len(self.target_moves(case_xml('anchor_crossing/call_is_a_shared_crossed_sibling'))), 1)

    def test_crossing_several_siblings_does_not_require_equal_neighbors(self):
        """Crossing several siblings does not require equal neighbors."""
        self.assertEqual(len(self.target_moves(case_xml('anchor_crossing/crossing_several_siblings_does_not_require_equal_neighbors'))), 1)

    def test_nested_wholly_common_conditional_is_a_sibling_boundary(self):
        """Nested wholly common conditional is a sibling boundary."""
        self.assertEqual(len(self.target_moves(case_xml('anchor_crossing/nested_wholly_common_conditional_is_a_sibling_boundary'))), 1)

    def test_common_loop_retains_its_own_crossing_evidence(self):
        """Common loop retains its own crossing evidence."""
        self.assertEqual(len(self.target_moves(case_xml('anchor_crossing/common_loop_retains_its_own_crossing_evidence'))), 1)

    def test_whole_loop_crosses_a_common_control_with_an_edited_body(self):
        """Whole loop crosses a common control with an edited body."""
        result = self.evaluate(case_xml('anchor_crossing/whole_loop_crosses_a_common_control_with_an_edited_body'))
        self.assertTrue(any(('while (running)' in text for move in result['moves'] for text in move['from_raw_texts'])))

    def test_unchanged_control_header_anchors_an_edited_body(self):
        """Unchanged control header anchors an edited body."""
        self.assertEqual(len(self.target_moves(case_xml('anchor_crossing/unchanged_control_header_anchors_an_edited_body'))), 1)

    def test_changed_control_header_does_not_borrow_body_anchors(self):
        """Changed control header does not borrow body anchors."""
        self.assertEqual(self.target_moves(case_xml('anchor_crossing/changed_control_header_does_not_borrow_body_anchors')), [])

    def test_different_common_blocks_provide_real_displacement(self):
        """Different common blocks provide real displacement."""
        self.assertEqual(len(self.target_moves(case_xml('anchor_crossing/different_common_blocks_provide_real_displacement'))), 1)

    def test_added_exclusive_wrapper_is_restructuring(self):
        """Added exclusive wrapper is restructuring."""
        self.assertEqual(self.target_moves(case_xml('anchor_crossing/added_exclusive_wrapper_is_restructuring')), [])

    def test_removed_else_wrapper_around_a_common_control_is_unwrapping(self):
        """Removed else wrapper around a common control is unwrapping."""
        result = self.evaluate(case_xml('anchor_crossing/removed_else_wrapper_around_a_common_control_is_unwrapping'))
        candidates = {item['candidate_id']: item for item in result['diagnostics']['candidates']}
        correspondence = next((item for item in result['diagnostics']['correspondences'] if candidates[item['delete_candidate_id']]['raw_text'] == TARGET_TEXT))
        self.assertEqual(correspondence['shadow_change'], 'restructured')
        self.assertEqual(correspondence['classification_reason'], 'ancestor_unwrapped')
        self.assertEqual(self.target_moves(case_xml('anchor_crossing/removed_else_wrapper_around_a_common_control_is_unwrapping')), [])

    def test_repeated_common_calls_do_not_supply_unique_crossing(self):
        """Repeated common calls do not supply unique crossing."""
        self.assertEqual(self.target_moves(case_xml('anchor_crossing/repeated_common_calls_do_not_supply_unique_crossing')), [])
if __name__ == '__main__':
    unittest.main()
