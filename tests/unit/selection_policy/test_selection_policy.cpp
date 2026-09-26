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
  return descendant_bundle_metrics{
      25358, 709, 44, 44, 30000, 30, 30000, 30, 30, 2};
}

} // namespace

int main() {
  try {
    proposal_rank_key larger{80000, 128, 96, 1, 1, 1000, 1, 1, 2};
    proposal_rank_key child{85000, 97, 89, 3, 1, 700, 3, 3, 4};
    require(proposal_rank_better(larger, child),
            "structural coverage should favor the coherent parent");

    proposal_rank_key first = larger;
    proposal_rank_key second = larger;
    first.minimum_id = 5;
    second.minimum_id = 6;
    require(proposal_rank_better(first, second),
            "candidate ids should deterministically break ties");

    require(descendant_bundle_preferred(weak_parent_bundle()),
            "strong independent children should replace a weak parent");

    auto low_coverage = weak_parent_bundle();
    low_coverage.child_delete_units = 20;
    low_coverage.child_insert_units = 20;
    require(!descendant_bundle_preferred(low_coverage),
            "a bundle must cover at least half of both parent endpoints");

    auto partition = weak_parent_bundle();
    partition.child_delete_units = 31;
    partition.child_insert_units = 31;
    require(!descendant_bundle_preferred(partition),
            "a near-complete partition should preserve the parent");

    auto small_confidence_gain = weak_parent_bundle();
    small_confidence_gain.parent_confidence_milli = 800;
    require(!descendant_bundle_preferred(small_confidence_gain),
            "children need a material confidence advantage");

    auto fragmented = weak_parent_bundle();
    fragmented.child_count = 8;
    require(!descendant_bundle_preferred(fragmented),
            "fragmentation cost should grow with the number of children");

    const stationary_exact_context stationary_delete{
        "same.cpp", "/unit/function/block", 3, 10, 20};
    const stationary_exact_context stationary_insert{
        "same.cpp", "/unit/function/block", 3, 21, 30};
    require(stationary_exact_pair(stationary_delete, stationary_insert),
            "an adjacent exact replacement in one nested context is stationary");

    stationary_exact_context moved_parent = stationary_insert;
    moved_parent.structural_parent_key = "/unit/other_function/block";
    require(!stationary_exact_pair(stationary_delete, moved_parent),
            "a changed structural parent is move evidence");

    stationary_exact_context moved_file = stationary_insert;
    moved_file.filename = "other.cpp";
    require(!stationary_exact_pair(stationary_delete, moved_file),
            "a changed file is move evidence");

    stationary_exact_context reordered = stationary_insert;
    reordered.diff_region_start_idx = 40;
    reordered.diff_region_end_idx   = 50;
    require(!stationary_exact_pair(stationary_delete, reordered),
            "separated regions may represent a same-parent reorder");

    stationary_exact_context file_root_delete = stationary_delete;
    stationary_exact_context file_root_insert = stationary_insert;
    file_root_delete.structural_parent_key = "/unit";
    file_root_insert.structural_parent_key = "/unit";
    file_root_delete.structural_parent_depth = 1;
    file_root_insert.structural_parent_depth = 1;
    require(!stationary_exact_pair(file_root_delete, file_root_insert),
            "a file root alone is insufficient stationary context");

    std::cout << "PASS selection policy tests\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL selection policy tests: " << error.what() << "\n";
    return 1;
  }
}
