#ifndef INCLUDED_MOVE_SUMMARY_HPP
#define INCLUDED_MOVE_SUMMARY_HPP

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "move_registry/selection_diagnostics.hpp"
#include "move_sequences.hpp"
#include "movement_classifier.hpp"

namespace srcmove {

inline constexpr std::uint32_t results_schema_version = 3;

struct result_endpoint {
  std::size_t candidate_id = 0;
  std::string revision_file;
  std::string xpath;
  std::string construct;
  std::string role;
  std::string raw_text;
};

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
  std::string identity_status = "unassessed";
  std::string identity_reason;
  std::vector<result_endpoint> original;
  std::vector<result_endpoint> modified;
  bool continuing_source_copy = false;
  bool unresolved_exact_residual = false;
  bool has_pair_location = false;
  movement_classification pair_location;
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

// Output items reference atomic evidence instead of copying endpoint bodies.
struct reported_move_entry {
  std::string move_id;
  std::string report_kind;
  std::vector<std::string> member_move_ids;
};

struct summary {
  std::size_t             move_pair_count = 0;
  std::vector<move_entry> moves;
  // Aggregation preserves atomic evidence and XML annotation IDs.
  std::vector<move_sequence> move_sequences;
  std::vector<reported_move_entry> reported_moves;
  content_relationship_counts reported_content_relationships;

  std::size_t annotated_region_count = 0;
  std::size_t regions_total     = 0;
  std::size_t candidates_total  = 0;
  std::size_t groups_total      = 0;
  group_kind_counts group_kinds;
  content_relationship_counts content_relationships;
  bool diagnostics_enabled = false;
  selection_diagnostics diagnostics;
  std::string min_granularity = "statement";
  std::size_t registered_candidate_count = 0;
  std::size_t active_candidate_count = 0;
  std::map<std::string, std::string> xpath_namespaces{
      {"src", "http://www.srcML.org/srcML/src"},
      {"diff", "http://www.srcML.org/srcDiff"}};
};

} // namespace srcmove
#endif
