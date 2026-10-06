"""Continuing statement shells distinguish supported and tentative move identity.

The exact flush call establishes displacement independently of the edited use.
These fixtures deliberately distinguish identity evidence from location evidence,
and exercise all three reporting modes through the shared integration harness.
"""
from __future__ import annotations
from tests.support.execution import require_success, require_tool
import unittest
from pathlib import Path
from tests.support.execution import artifact_directory, run_logged
import xml.etree.ElementTree as ET
from tests.support import behavior as fixture
from tests.support.readable_cases import case_sources, evaluate_case
from benchmarking.tooling import find_srcdiff
OLD, NEW = ('old_count', 'new_count')

class ContinuingIdentityTests(unittest.TestCase):

    def declaration_moves(self, payload: dict) -> list[dict]:
        return [move for move in payload['moves'] if f'int {OLD} = 1;' in move['from_raw_texts']]

    def assert_rejected(self, payload: dict) -> None:
        self.assertEqual(self.declaration_moves(payload), [])

    def assert_report_identity(self, payload: dict, move: dict) -> None:
        reports = [report for report in payload['reported_moves'] if move['move_id'] in report['member_move_ids']]
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]['identity_status'], move['identity_status'])
        self.assertEqual(reports[0]['identity_reason'], move['identity_reason'])

    def assert_tentative(self, payload: dict) -> dict:
        moves = self.declaration_moves(payload)
        self.assertEqual(len(moves), 1)
        move = moves[0]
        self.assertEqual(move['identity_status'], 'tentative')
        self.assertEqual(move['identity_reason'], 'uncorroborated_declaration')
        self.assert_report_identity(payload, move)
        return move

    def test_independent_continuing_use_corroborates_small_renamed_move(self):
        """Independent continuing use corroborates small renamed move."""
        payload = evaluate_case(self, 'continuing_identity/independent_continuing_use_corroborates_small_renamed_move')
        moves = self.declaration_moves(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['content_relationship'], 'type2c')
        self.assertEqual(moves[0]['to_raw_texts'], [f'int {NEW} = 1;'])
        self.assertEqual(moves[0]['identity_status'], 'corroborated')
        self.assertEqual(moves[0]['identity_reason'], 'continuing_name_corroborated')
        self.assert_report_identity(payload, moves[0])

    def test_crossed_anchor_alone_does_not_establish_renamed_identity(self):
        """Crossed anchor alone does not establish renamed identity."""
        self.assert_tentative(evaluate_case(self, 'continuing_identity/crossed_anchor_alone_does_not_establish_renamed_identity'))

    def test_unchanged_uses_contradict_unrelated_same_shape_declarations(self):
        """Unchanged uses contradict unrelated same shape declarations."""
        self.assert_rejected(evaluate_case(self, 'continuing_identity/unchanged_uses_contradict_unrelated_same_shape_declarations'))

    def test_continuing_replacement_to_different_partner_rejects_move(self):
        """Continuing replacement to different partner rejects move."""
        self.assert_rejected(evaluate_case(self, 'continuing_identity/continuing_replacement_to_different_partner_rejects_move'))

    def test_conflicting_replacements_cannot_corroborate_weak_declaration(self):
        """Conflicting replacements cannot corroborate weak declaration."""
        self.assert_tentative(evaluate_case(self, 'continuing_identity/conflicting_replacements_cannot_corroborate_weak_declaration'))

    def test_many_to_one_replacement_evidence_is_not_independent_identity(self):
        """Many to one replacement evidence is not independent identity."""
        self.assert_tentative(evaluate_case(self, 'continuing_identity/many_to_one_replacement_evidence_is_not_independent_identity'))

    def test_evidence_from_other_function_cannot_corroborate_move(self):
        """Evidence from other function cannot corroborate move."""
        self.assert_tentative(evaluate_case(self, 'continuing_identity/evidence_from_other_function_cannot_corroborate_move'))

    def test_shadow_scope_evidence_cannot_override_local_correspondence(self):
        """Shadow scope evidence cannot override local correspondence."""
        moves = self.declaration_moves(evaluate_case(self, 'continuing_identity/shadow_scope_evidence_cannot_override_local_correspondence'))
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['content_relationship'], 'type2c')

    def test_separate_deleted_inserted_uses_do_not_supply_continuing_evidence(self):
        """Separate deleted inserted uses do not supply continuing evidence."""
        self.assert_tentative(evaluate_case(self, 'continuing_identity/separate_deleted_inserted_uses_do_not_supply_continuing_evidence'))

    def test_changed_literal_use_is_not_reliable_rename_evidence(self):
        """Changed literal use is not reliable rename evidence."""
        self.assert_tentative(evaluate_case(self, 'continuing_identity/changed_literal_use_is_not_reliable_rename_evidence'))

    def test_contradiction_gate_also_rejects_larger_normalized_statement(self):
        """Contradiction gate also rejects larger normalized statement."""
        payload = evaluate_case(self, 'continuing_identity/contradiction_gate_also_rejects_larger_normalized_statement')
        self.assertEqual(payload['moves'], [])

    def test_qualified_member_contradiction_crosses_sibling_blocks(self):
        """Qualified member contradiction crosses sibling blocks."""
        payload = evaluate_case(self, 'continuing_identity/qualified_member_contradiction_crosses_sibling_blocks')
        self.assertEqual(payload['moves'], [])

    def test_different_receiver_evidence_cannot_reject_member_move(self):
        """Different receiver evidence cannot reject member move."""
        payload = evaluate_case(self, 'continuing_identity/different_receiver_evidence_cannot_reject_member_move')
        self.assertEqual(len(payload['moves']), 1)
        self.assertEqual(payload['moves'][0]['content_relationship'], 'type2c')

    def test_local_identifier_evidence_cannot_reject_qualified_member_move(self):
        """Local identifier evidence cannot reject qualified member move."""
        payload = evaluate_case(self, 'continuing_identity/local_identifier_evidence_cannot_reject_qualified_member_move')
        self.assertEqual(len(payload['moves']), 1)
        self.assertEqual(payload['moves'][0]['content_relationship'], 'type2c')

    def test_member_evidence_cannot_corroborate_same_spelled_local_declaration(self):
        """Member evidence cannot corroborate same spelled local declaration."""
        self.assert_tentative(evaluate_case(self, 'continuing_identity/member_evidence_cannot_corroborate_same_spelled_local_declaration'))

    def test_qualified_member_contradiction_inside_for_rejects_outer_match(self):
        """Qualified member contradiction inside for rejects outer match."""
        payload = evaluate_case(self, 'continuing_identity/qualified_member_contradiction_inside_for_rejects_outer_match')
        self.assertEqual(payload['moves'], [])

    def test_fragmented_identifier_does_not_corroborate_unrelated_full_names(self):
        """Fragmented identifier does not corroborate unrelated full names."""
        self.assert_tentative(evaluate_case(self, 'continuing_identity/fragmented_identifier_does_not_corroborate_unrelated_full_names'))

    def test_corroborated_move_has_stronger_utility_than_tentative_same_content(self):
        """Corroborated move has stronger utility than tentative same content."""
        tentative = self.assert_tentative(evaluate_case(self, 'continuing_identity/utility_tentative'))
        supported = self.declaration_moves(evaluate_case(self, 'continuing_identity/utility_corroborated'))[0]
        self.assertEqual(tentative['matched_units'], supported['matched_units'])
        self.assertEqual(tentative['confidence_milli'], supported['confidence_milli'])
        self.assertLess(tentative['selection_utility'], supported['selection_utility'])

    def test_tentative_identity_still_requires_displacement(self):
        """Tentative identity still requires displacement."""
        payload = evaluate_case(self, 'continuing_identity/tentative_identity_still_requires_displacement')
        self.assert_rejected(payload)

    def test_exact_alternative_wins_shared_endpoint_over_tentative_rename(self):
        """Exact alternative wins shared endpoint over tentative rename."""
        payload = evaluate_case(self, 'continuing_identity/exact_alternative_wins_shared_endpoint_over_tentative_rename')
        moves = self.declaration_moves(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['content_relationship'], 'type1')
        self.assertEqual(moves[0]['to_raw_texts'], [f'int {OLD} = 1;'])
        self.assertEqual(moves[0]['identity_status'], 'exact')
        self.assert_report_identity(payload, moves[0])

    def test_tentative_type2_does_not_reserve_endpoint_against_stronger_type3(self):
        """Tentative type2 does not reserve endpoint against stronger type3."""
        payload = evaluate_case(self, 'continuing_identity/tentative_type2_does_not_reserve_endpoint_against_stronger_type3')
        moves = [move for move in payload['moves'] if any((text.startswith(f'int {OLD} = compute(') for text in move['from_raw_texts']))]
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['content_relationship'], 'type3')
        self.assertTrue(moves[0]['to_raw_texts'][0].startswith(f'int {OLD} = compute('))
        self.assertIn('+ 1;', moves[0]['to_raw_texts'][0])

class ContinuingIdentitySourceTests(unittest.TestCase):
    """Regenerate structured differences, preserving source-reviewed endpoint roles."""

    def evaluate_sources(self, before: str, after: str, *, mixed_use: bool) -> dict:
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
        src = '{http://www.srcML.org/srcML/src}'
        diff = '{http://www.srcML.org/srcDiff}'
        tree = ET.fromstring(xml)
        for side, name in [('delete', OLD), ('insert', NEW)]:
            candidates = [node for wrapper in tree.iter(diff + side) for node in wrapper.iter(src + 'decl_stmt')]
            self.assertEqual(len(candidates), 1)
            self.assertIn(name, ''.join(candidates[0].itertext()))
        uses = [node for node in tree.iter(src + 'expr_stmt') if ''.join(node.itertext()).startswith('consume(')]
        self.assertEqual(len(uses), 1)
        self.assertEqual(any((node.tag == diff + 'delete' for node in uses[0].iter())), mixed_use)
        self.assertEqual(any((node.tag == diff + 'insert' for node in uses[0].iter())), mixed_use)
        return fixture.evaluate(self, xml)

    def test_srcdiff_moved_renamed_declaration_has_continuing_use_support(self):
        """Srcdiff moved renamed declaration has continuing use support."""
        payload = self.evaluate_sources(case_sources('continuing_identity/srcdiff_moved_renamed_declaration_has_continuing_use_support')[0]['source.cpp'], case_sources('continuing_identity/srcdiff_moved_renamed_declaration_has_continuing_use_support')[1]['source.cpp'], mixed_use=True)
        moves = ContinuingIdentityTests().declaration_moves(payload)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]['content_relationship'], 'type2c')
        self.assertEqual(moves[0]['to_raw_texts'], ['int new_count = 1;'])

    def test_srcdiff_same_shape_declarations_with_continuing_distinct_names_rejected(self):
        """Srcdiff same shape declarations with continuing distinct names rejected."""
        payload = self.evaluate_sources(case_sources('continuing_identity/srcdiff_same_shape_declarations_with_continuing_distinct_names_rejected')[0]['source.cpp'], case_sources('continuing_identity/srcdiff_same_shape_declarations_with_continuing_distinct_names_rejected')[1]['source.cpp'], mixed_use=False)
        ContinuingIdentityTests().assert_rejected(payload)
if __name__ == '__main__':
    unittest.main()
