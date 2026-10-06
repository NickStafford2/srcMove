"""Detector expectations expressed with named occurrences in source fixtures."""
import unittest

from tests.support.scenarios import load_scenario


def expect_two_new_copies(case):
    case.expect_copy_group(
        relationship='type1', reason='continuing_source_copy',
        origins=['first.repeat_work', 'second.repeat_work'],
        destinations=['extra_a.repeat_work', 'extra_b.repeat_work'],
    )
    case.expect_group_count(1)
    case.expect_no_sequences()


def expect_adjacent_distinct_copies(case):
    case.expect_copy_group(
        relationship='type1', reason='continuing_source_copy',
        origins=['first.repeat_work'], destinations=['extra.repeat_work'],
    )
    case.expect_copy_group(
        relationship='type1', reason='continuing_source_copy',
        origins=['first.other_repeat'], destinations=['extra.other_repeat'],
    )
    case.expect_group_count(2)
    case.expect_no_sequences()
    case.expect_atomic_reports(2)


def expect_reorder_with_stationary_repeat(case):
    case.expect_move(origin='first.repeat_work', destination='first.repeat_work', relationship='type1')
    case.expect_group_count(1)


def expect_duplicate_basenames(case):
    case.expect_group_count(2)
    case.expect_relocated_declaration('a/Case.cpp', 'int target = source + 17;')
    case.expect_relocated_declaration('b/Case.cpp', 'int secondary = source + 29;')


class ReadableScenarioTests(unittest.TestCase):
    def test_two_existing_calls_produce_two_new_copies(self):
        """Two existing calls produce two new copies."""
        case = load_scenario(self, 'two_existing_calls_two_new_copies')
        expect_two_new_copies(case)

    def test_adjacent_copies_remain_separate_groups(self):
        """Adjacent copies remain separate groups."""
        case = load_scenario(self, 'adjacent_distinct_copies')
        expect_adjacent_distinct_copies(case)

    def test_reorder_selects_the_moving_occurrence(self):
        """Reorder selects the moving occurrence."""
        case = load_scenario(self, 'reorder_with_stationary_repeat')
        expect_reorder_with_stationary_repeat(case)

    def test_duplicate_basenames_preserve_each_full_path(self):
        """Duplicate basenames preserve each full path."""
        case = load_scenario(self, 'duplicate_basenames')
        expect_duplicate_basenames(case)
