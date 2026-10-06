#include "move_registry/selection_policy.hpp"

#include <iostream>
#include <stdexcept>

using namespace srcmove;

namespace {

void require(bool condition, const char *message) {
  if (!condition)
    throw std::runtime_error(message);
}

descendant_bundle_metrics weak_parent_bundle() {
  descendant_bundle_metrics metrics;
  metrics.parent_utility = 25358;
  metrics.parent_confidence_milli = 709;
  metrics.parent_delete_units = 44;
  metrics.parent_insert_units = 44;
  metrics.child_utility_sum = 30000;
  metrics.child_matched_units = 30;
  metrics.child_weighted_confidence = 30000;
  metrics.child_delete_units = 30;
  metrics.child_insert_units = 30;
  metrics.child_count = 2;
  return metrics;
}

proposal_rank_key coherent_parent_rank() {
  proposal_rank_key parent;
  parent.utility = 80000;
  parent.explanatory_units = 128;
  parent.matched_units = 96;
  parent.evidence_strength = 1;
  parent.source_construct = 1;
  parent.covered_span = 1000;
  parent.minimum_id = 1;
  parent.delete_id = 1;
  parent.insert_id = 2;
  return parent;
}

void test_structural_coverage_favors_coherent_parent() {
  auto parent = coherent_parent_rank();
  proposal_rank_key child;
  child.utility = 85000;
  child.explanatory_units = 97;
  child.matched_units = 89;
  child.evidence_strength = 3;
  child.source_construct = 1;
  child.covered_span = 700;
  child.minimum_id = 3;
  child.delete_id = 3;
  child.insert_id = 4;
  require(proposal_rank_better(parent, child),
          "structural coverage should favor the coherent parent");
}

void test_candidate_ids_break_equal_rank_ties() {
  auto first = coherent_parent_rank();
  auto second = coherent_parent_rank();
  first.minimum_id = 5;
  second.minimum_id = 6;
  require(proposal_rank_better(first, second),
          "candidate ids should deterministically break ties");
}

void test_strong_independent_children_replace_weak_parent() {
  require(descendant_bundle_preferred(weak_parent_bundle()),
          "strong independent children should replace a weak parent");
}

void test_insufficient_child_coverage_preserves_parent() {
  auto low_coverage = weak_parent_bundle();
  low_coverage.child_delete_units = 20;
  low_coverage.child_insert_units = 20;
  require(!descendant_bundle_preferred(low_coverage),
          "a bundle must cover at least half of both parent endpoints");
}

void test_near_complete_child_partition_preserves_parent() {
  auto partition = weak_parent_bundle();
  partition.child_delete_units = 31;
  partition.child_insert_units = 31;
  require(!descendant_bundle_preferred(partition),
          "a near-complete partition should preserve the parent");
}

void test_insufficient_child_confidence_advantage_preserves_parent() {
  auto small_confidence_gain = weak_parent_bundle();
  small_confidence_gain.parent_confidence_milli = 800;
  require(!descendant_bundle_preferred(small_confidence_gain),
          "children need a material confidence advantage");
}

void test_fragmentation_cost_preserves_parent() {
  auto fragmented = weak_parent_bundle();
  fragmented.child_count = 8;
  require(!descendant_bundle_preferred(fragmented),
          "fragmentation cost should grow with the number of children");
}

} // namespace

int main() {
  try {
    test_structural_coverage_favors_coherent_parent();
    test_candidate_ids_break_equal_rank_ties();
    test_strong_independent_children_replace_weak_parent();
    test_insufficient_child_coverage_preserves_parent();
    test_near_complete_child_partition_preserves_parent();
    test_insufficient_child_confidence_advantage_preserves_parent();
    test_fragmentation_cost_preserves_parent();
    std::cout << "PASS selection policy tests\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL selection policy tests: " << error.what() << "\n";
    return 1;
  }
}
