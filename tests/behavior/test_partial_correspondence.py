"""Repeated exact groups retain supported pairs and explicit residual copies."""
from __future__ import annotations
import json
from pathlib import Path
from tests.support.execution import artifact_directory, run_logged
import unittest
from benchmarking.tooling import find_srcmove
from tests.support import behavior as fixture
from tests.support.readable_cases import evaluate_case

class PartialCorrespondenceTests(unittest.TestCase):

    def repeated(self, payload):
        return [move for move in payload['moves'] if move['from_raw_texts'] and all((raw == 'repeat_work(state);' for raw in move['from_raw_texts']))]

    def test_continuing_loop_with_two_added_copies_retains_copy_origin(self):
        """Continuing loop with two added copies retains copy origin."""
        payload = evaluate_case(self, 'partial_correspondence/continuing_loop_with_two_added_copies_retains_copy_origin')
        copies = self.repeated(payload)
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]['selection_reason'], 'continuing_source_copy')
        self.assertEqual(len(copies[0]['from_xpaths']), 1)
        self.assertEqual(len(copies[0]['to_xpaths']), 2)
        self.assertTrue(all(('diff:insert[1]' not in path for path in copies[0]['to_xpaths'])))
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 1)

    def test_single_added_copy_is_not_disguised_as_unique_move(self):
        """Single added copy is not disguised as unique move."""
        payload = evaluate_case(self, 'partial_correspondence/single_added_copy_is_not_disguised_as_unique_move')
        copies = self.repeated(payload)
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]['selection_reason'], 'continuing_source_copy')
        self.assertEqual(len(copies[0]['to_xpaths']), 1)
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 1)
        self.assertEqual(payload['move_sequences'], [])

    def test_copy_inside_same_block_and_interval_is_retained(self):
        """Copy inside same block and interval is retained."""
        payload = evaluate_case(self, 'partial_correspondence/copy_inside_same_block_and_interval_is_retained')
        self.assertEqual(len(self.repeated(payload)), 1)
        self.assertEqual(self.repeated(payload)[0]['selection_reason'], 'continuing_source_copy')

    def test_many_to_few_consumes_continuation_without_choosing_deleted_copy(self):
        """Many to few consumes continuation without choosing deleted copy."""
        payload = evaluate_case(self, 'partial_correspondence/many_to_few_consumes_continuation_without_choosing_deleted_copy')
        self.assertEqual(self.repeated(payload), [])

    def test_partial_neighbor_resolution_does_not_claim_residual_by_elimination(self):
        """Partial neighbor resolution does not claim residual by elimination."""
        payload = evaluate_case(self, 'partial_correspondence/partial_neighbor_resolution_does_not_claim_residual_by_elimination')
        repeated = self.repeated(payload)
        self.assertEqual(len(repeated), 2)
        self.assertEqual({move['selection_reason'] for move in repeated}, {'exact_neighbor_correspondence', 'unresolved_exact_residual'})
        residual = next((move for move in repeated if move['selection_reason'] == 'unresolved_exact_residual'))
        self.assertEqual(len(residual['from_xpaths']), 1)
        self.assertEqual(len(residual['to_xpaths']), 1)
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 1)

    def test_unresolved_wrapper_alias_does_not_claim_identity_by_elimination(self):
        """Unresolved wrapper alias does not claim identity by elimination."""
        payload = evaluate_case(self, 'partial_correspondence/unresolved_wrapper_alias_does_not_claim_identity_by_elimination')
        residual = next((move for move in self.repeated(payload) if move['selection_reason'] == 'unresolved_exact_residual'))
        self.assertEqual(payload['group_kinds']['copy_or_repeat'], 1)
        with artifact_directory(case_id=self.id()) as directory:
            xml, results = (Path(directory) / 'input.xml', Path(directory) / 'results.json')
            xml.write_text(self.last_xml)
            command = [str(find_srcmove(fixture.REPO_ROOT, None)), str(xml), '--results', str(results), '--results-only', '--diagnostics']
            run_logged(command, check=True, capture_output=True, text=True)
            diagnostics = json.loads(results.read_text())['diagnostics']
        unresolved_path = residual['from_xpaths'][0]
        unresolved_ids = {candidate['candidate_id'] for candidate in diagnostics['candidates'] if candidate['side'] == 'delete' and (candidate['xpath'] == unresolved_path or (candidate['role'] == 'single_child_wrapper' and unresolved_path.startswith(candidate['xpath'] + '/')))}
        self.assertEqual(len(unresolved_ids), 2)
        self.assertFalse(any((row['delete_candidate_id'] in unresolved_ids for row in diagnostics['correspondences'])))

    def test_unpaired_origins_prevent_claiming_residual_destinations_are_new_copies(self):
        """Unpaired origins prevent claiming residual destinations are new copies."""
        payload = evaluate_case(self, 'partial_correspondence/unpaired_origins_prevent_claiming_residual_destinations_are_new_copies')
        self.assertFalse(any((move['selection_reason'] == 'continuing_source_copy' for move in self.repeated(payload))))

    def test_unresolved_cross_file_copy_capability_is_preserved(self):
        """Unresolved cross file copy capability is preserved."""
        payload = evaluate_case(self, 'partial_correspondence/unresolved_cross_file_copy_capability_is_preserved')
        copies = self.repeated(payload)
        self.assertEqual(len(copies), 1)
        self.assertEqual(len(copies[0]['from_xpaths']), 2)
        self.assertEqual(len(copies[0]['to_xpaths']), 3)
        self.assertEqual(copies[0]['selection_reason'], 'greedy_utility')

    def test_real_reorder_keeps_original_unique_neighbor_partners(self):
        """Real reorder keeps original unique neighbor partners."""
        payload = evaluate_case(self, 'partial_correspondence/real_reorder_keeps_original_unique_neighbor_partners')
        repeated = self.repeated(payload)
        self.assertEqual(len(repeated), 2)
        self.assertTrue(all((move['selection_reason'] == 'exact_neighbor_correspondence' for move in repeated)))
if __name__ == '__main__':
    unittest.main()
