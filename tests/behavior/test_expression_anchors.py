"""Unchanged expression statements provide movement location evidence."""
from __future__ import annotations
import unittest
from tests.support.readable_cases import evaluate_case

class ExpressionAnchorTests(unittest.TestCase):

    def moved(self, payload: dict) -> list[dict]:
        return [move for move in payload['moves'] if 'int payload = 109;' in move['from_raw_texts']]

    def test_crossing_unique_unchanged_call_reports_move(self):
        """Crossing unique unchanged call reports move."""
        payload = evaluate_case(self, 'expression_anchors/crossing_unique_unchanged_call_reports_move')
        self.assertEqual(len(self.moved(payload)), 1)
        self.assertEqual(self.moved(payload)[0]['content_relationship'], 'type1')

    def test_same_side_of_call_remains_stationary(self):
        """Same side of call remains stationary."""
        payload = evaluate_case(self, 'expression_anchors/same_side_of_call_remains_stationary')
        self.assertEqual(self.moved(payload), [])

    def test_repeated_calls_cannot_establish_crossing(self):
        """Repeated calls cannot establish crossing."""
        payload = evaluate_case(self, 'expression_anchors/repeated_calls_cannot_establish_crossing')
        self.assertEqual(self.moved(payload), [])

    def test_edited_call_cannot_establish_crossing(self):
        """Edited call cannot establish crossing."""
        payload = evaluate_case(self, 'expression_anchors/edited_call_cannot_establish_crossing')
        self.assertEqual(self.moved(payload), [])
if __name__ == '__main__':
    unittest.main()
