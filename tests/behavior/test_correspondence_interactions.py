"""Hand-authored alternative XML interaction contracts.

Whole-loop replacements are legal coarse encodings, not assertions about default
srcDiff output. Common markup and regenerated source provide paired controls.
"""
from __future__ import annotations
from tests.support.execution import require_success, require_tool
from pathlib import Path
from tests.support.execution import artifact_directory, run_logged
import unittest
import xml.etree.ElementTree as ET
from benchmarking.tooling import find_srcdiff
from tests.support import behavior as fixture
from tests.support.readable_cases import case_xml, case_sources, evaluate_case
TEXT = 'repeat_work(state);'

class CorrespondenceInteractionTests(unittest.TestCase):

    def targets(self, payload):
        return [m for m in payload['moves'] if m['from_raw_texts'] == [TEXT] or (m['from_raw_texts'] and all((t == TEXT for t in m['from_raw_texts'])))]

    def test_two_continuing_origins_preserve_only_added_copy_destination(self):
        """Two continuing origins preserve only added copy destination."""
        payload = evaluate_case(self, 'correspondence_interactions/two_continuing_origins_preserve_only_added_copy_destination')
        copies = self.targets(payload)
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertEqual(copy['selection_reason'], 'continuing_source_copy')
        self.assertEqual(copy['from_raw_texts'], [TEXT, TEXT])
        self.assertEqual(copy['to_raw_texts'], [TEXT])
        self.assertEqual(len(set(copy['from_xpaths'])), 2)
        self.assertEqual({index for index in (1, 2) if any((f'diff:delete[{index}]' in path for path in copy['from_xpaths']))}, {1, 2})
        self.assertEqual(len(copy['to_xpaths']), 1)
        self.assertIn('diff:insert[3]', copy['to_xpaths'][0])
        self.assertEqual(payload['move_sequences'], [])

    def test_padded_reorder_inside_paired_replaced_loop_remains_a_move(self):
        """Padded reorder inside paired replaced loop remains a move."""
        payload = evaluate_case(self, 'correspondence_interactions/padded_reorder_inside_paired_replaced_loop_remains_a_move')
        moves = self.targets(payload)
        self.assertEqual(len(moves), 1, 'R crosses two continuing calls in the first loop')
        self.assertEqual(moves[0]['from_raw_texts'], [TEXT])
        self.assertEqual(moves[0]['to_raw_texts'], [TEXT])
        self.assertIn('diff:delete[1]', moves[0]['from_xpaths'][0])
        self.assertIn('diff:insert[1]', moves[0]['to_xpaths'][0])

    def test_padded_stationary_replaced_loops_do_not_claim_moves_or_copies(self):
        """Padded stationary replaced loops do not claim moves or copies."""
        self.assertEqual(self.targets(evaluate_case(self, 'correspondence_interactions/padded_stationary_replaced_loops_do_not_claim_moves_or_copies')), [])

    def test_default_srcdiff_pipeline_preserves_padded_loop_reorder(self):
        """Default srcdiff pipeline preserves padded loop reorder."""
        sources = case_sources('correspondence_interactions/default_srcdiff_pipeline_preserves_padded_loop_reorder')
        before, after = (side['source.cpp'] for side in sources)
        srcdiff = find_srcdiff(fixture.REPO_ROOT)
        require_tool(srcdiff)
        with artifact_directory(case_id=self.id()) as directory:
            root = Path(directory)
            for side, source in [('before', before), ('after', after)]:
                (root / side).mkdir()
                (root / side / 'source.cpp').write_text(source)
            output = root / 'srcdiff.xml'
            result = run_logged([str(srcdiff), str(root / 'before'), str(root / 'after'), '-o', str(output)], capture_output=True, text=True)
            require_success(result)
            xml = output.read_text()
        tree = ET.fromstring(xml)
        src, diff = ('{http://www.srcML.org/srcML/src}', '{http://www.srcML.org/srcDiff}')
        for side in ('delete', 'insert'):
            targets = [node for wrapper in tree.iter(diff + side) for node in wrapper.iter(src + 'expr_stmt') if ''.join(node.itertext()) == TEXT]
            self.assertEqual(len(targets), 1, 'Upstream must retain the whole reordered statement')
        moves = self.targets(fixture.evaluate(self, xml))
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['from_raw_texts'], [TEXT])
        self.assertEqual(moves[0]['to_raw_texts'], [TEXT])
        self.assertIn('src:while[1]', moves[0]['from_xpaths'][0])
        self.assertIn('src:while[1]', moves[0]['to_xpaths'][0])

    def assert_no_invented_partial_partner(self, xml):
        payload = fixture.evaluate(self, xml)
        for move in self.targets(payload):
            self.assertNotEqual(move['selection_reason'], 'continuing_source_copy')
            self.assertNotEqual(move['selection_reason'], 'exact_neighbor_correspondence')
        target_ids = {move['move_id'] for move in self.targets(payload)}
        self.assertTrue(all((target_ids.isdisjoint(sequence['member_move_ids']) for sequence in payload['move_sequences'])))

    def test_split_unique_seeds_cannot_establish_one_parent_partner(self):
        """Split unique seeds cannot establish one parent partner."""
        self.assert_no_invented_partial_partner(case_xml('correspondence_interactions/split_unique_seeds_cannot_establish_one_parent_partner'))

    def test_merged_unique_seeds_cannot_establish_two_parent_partners(self):
        """Merged unique seeds cannot establish two parent partners."""
        self.assert_no_invented_partial_partner(case_xml('correspondence_interactions/merged_unique_seeds_cannot_establish_two_parent_partners'))

    def test_crossed_unique_seed_order_is_not_stationary_identity_evidence(self):
        """Crossed unique seed order is not stationary identity evidence."""
        self.assert_no_invented_partial_partner(case_xml('correspondence_interactions/crossed_unique_seed_order_is_not_stationary_identity_evidence'))
if __name__ == '__main__':
    unittest.main()
