"""Output modes and exact XML annotations for the same readable scenarios."""
import unittest

from tests.behavior import test_readable_scenarios as expectations
from tests.support.scenarios import load_scenario


OUTPUT_MODES = ('ordinary', 'diagnostic', 'results_only')


class ScenarioOutputContractTests(unittest.TestCase):
    def test_two_new_copies_output_contract(self):
        """Two new copies output contract."""
        case = load_scenario(self, 'two_existing_calls_two_new_copies', modes=OUTPUT_MODES)
        expectations.expect_two_new_copies(case)
        case.assert_output_contracts()

    def test_adjacent_distinct_copies_output_contract(self):
        """Adjacent distinct copies output contract."""
        case = load_scenario(self, 'adjacent_distinct_copies', modes=OUTPUT_MODES)
        expectations.expect_adjacent_distinct_copies(case)
        case.assert_output_contracts()

    def test_reorder_with_stationary_repeat_output_contract(self):
        """Reorder with stationary repeat output contract."""
        case = load_scenario(self, 'reorder_with_stationary_repeat', modes=OUTPUT_MODES)
        expectations.expect_reorder_with_stationary_repeat(case)
        case.assert_output_contracts()

    def test_duplicate_basenames_output_contract(self):
        """Duplicate basenames output contract."""
        case = load_scenario(self, 'duplicate_basenames', modes=OUTPUT_MODES)
        expectations.expect_duplicate_basenames(case)
        case.assert_output_contracts()
