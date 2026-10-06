#ifndef INCLUDED_MOVE_SUMMARY_HPP
#define INCLUDED_MOVE_SUMMARY_HPP

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "move_registry/selection_diagnostics.hpp"
#include "move_sequences.hpp"

namespace srcmove {

inline constexpr std::uint32_t results_schema_version = 2;

struct move_entry {
  std::string              move_id;
  std::string              content_relationship;
  std::uint32_t            confidence_milli = 0;
  std::uint64_t            selection_utility = 0;
  std::uint32_t            matched_units = 0;
  std::string              selection_reason;
  std::vector<std::string> from_xpaths;
  std::vector<std::string> to_xpaths;
  std::vector<std::string> from_raw_texts;
  std::vector<std::string> to_raw_texts;
};

struct group_kind_counts {
  std::size_t move_1_to_1    = 0;
  std::size_t moves_many     = 0;
  std::size_t delete_only    = 0;
  std::size_t insert_only    = 0;
  std::size_t copy_or_repeat = 0;
  std::size_t ambiguous      = 0;
};

struct content_relationship_counts {
  std::size_t type1 = 0;
  std::size_t type2c = 0;
  std::size_t type3 = 0;
};

// Primary reporting units. Ordered sequences retain positional member links;
// their endpoint arrays are not content-equivalence partner sets.
struct reported_move_entry {
  std::string move_id;
  std::string report_kind;
  std::string content_relationship;
  std::vector<std::string> member_move_ids;
  std::vector<std::string> from_xpaths;
  std::vector<std::string> to_xpaths;
  std::vector<std::string> from_raw_texts;
  std::vector<std::string> to_raw_texts;
};

struct summary {
  std::size_t             move_count = 0; // Backward-compatible alias for move_group_count.
  std::size_t             move_group_count = 0;
  std::size_t             move_pair_count = 0;
  std::vector<move_entry> moves;
  // Additive sequence reporting; original moves/counts retain their meanings.
  std::vector<move_sequence> move_sequences;
  std::size_t sequence_cluster_count = 0;
  std::size_t sequence_reporting_unit_count = 0;
  std::vector<reported_move_entry> reported_moves;
  std::size_t reported_move_count = 0;
  content_relationship_counts reported_content_relationships;

  std::size_t annotated_regions = 0; // Backward-compatible alias for annotated_region_count.
  std::size_t annotated_region_count = 0;
  std::size_t regions_total     = 0;
  std::size_t candidates_total  = 0;
  std::size_t groups_total      = 0;
  group_kind_counts group_kinds;
  content_relationship_counts content_relationships;
  bool diagnostics_enabled = false;
  selection_diagnostics diagnostics;
};

} // namespace srcmove
#endif
