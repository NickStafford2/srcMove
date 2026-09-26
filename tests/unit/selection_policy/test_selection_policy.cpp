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

    const local_replacement_context local_delete{"same.cpp", 3, 10, 20};
    const local_replacement_context local_insert{"same.cpp", 3, 21, 30};
    require(local_replacement_pair(local_delete, local_insert),
            "adjacent regions in one nested file context are a local replacement");

    local_replacement_context moved_file = local_insert;
    moved_file.filename = "other.cpp";
    require(!local_replacement_pair(local_delete, moved_file),
            "a changed file is move evidence");

    local_replacement_context reordered = local_insert;
    reordered.diff_region_start_idx = 40;
    reordered.diff_region_end_idx   = 50;
    require(!local_replacement_pair(local_delete, reordered),
            "separated regions may represent a same-parent reorder");

    local_replacement_context file_root_delete = local_delete;
    local_replacement_context file_root_insert = local_insert;
    file_root_delete.structural_parent_depth = 1;
    file_root_insert.structural_parent_depth = 1;
    require(!local_replacement_pair(file_root_delete, file_root_insert),
            "a file root alone is insufficient stationary context");

    local_replacement_context insert_then_delete = local_delete;
    insert_then_delete.diff_region_start_idx = 31;
    insert_then_delete.diff_region_end_idx   = 40;
    require(local_replacement_pair(insert_then_delete, local_insert),
            "local replacement recognition is independent of region polarity");

    std::cout << "PASS selection policy tests\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL selection policy tests: " << error.what() << "\n";
    return 1;
  }
}
