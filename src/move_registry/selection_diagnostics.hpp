#ifndef INCLUDED_MOVE_SELECTION_DIAGNOSTICS_HPP
#define INCLUDED_MOVE_SELECTION_DIAGNOSTICS_HPP

#include <cstddef>
#include <string>
#include <vector>

namespace srcmove {

struct candidate_diagnostic {
  std::size_t candidate_id = 0;
  std::string side;
  std::string filename;
  std::string xpath;
  std::string construct;
  std::string role;
  std::string raw_text;
  bool        type3_eligible = false;
  std::size_t line_units = 0;
  std::size_t token_units = 0;
};

// A blind equivalence group is an observation, never a production proposal.
// Endpoint lists may contain consistent pairs; the count excludes those pairs.
struct type2b_group_diagnostic {
  std::vector<std::size_t> delete_candidate_ids;
  std::vector<std::size_t> insert_candidate_ids;
  std::size_t blind_only_pair_count = 0;
  std::string location_change; // populated only for a unique blind-only pair
  std::string location_reason;
};

struct type3_pair_diagnostic {
  std::size_t del_candidate_id = 0;
  std::size_t ins_candidate_id = 0;
  std::string outcome;
  std::size_t common_lines = 0;
  std::size_t maximum_lines = 0;
  std::size_t common_tokens = 0;
  std::size_t maximum_tokens = 0;
};

struct endpoint_context_diagnostic {
  std::string revision_file;
  std::string semantic_container_id;
  std::string semantic_container_label;
  std::string previous_common_anchor_id;
  std::string next_common_anchor_id;
  std::vector<std::string> meaningful_ancestors;
  bool ancestor_summary_interpretable = false;
};

struct correspondence_diagnostic {
  std::size_t delete_candidate_id = 0;
  std::size_t insert_candidate_id = 0;
  std::string correspondence_kind;
  std::string cardinality;
  std::string current_result;
  std::string shadow_change;
  std::string classification_reason;
  std::string file_observation;
  std::string semantic_container_observation;
  std::string anchor_interval_observation;
  std::string relative_order_observation;
  std::string ancestor_observation;
  bool carried_by_parent = false;
  endpoint_context_diagnostic before_context;
  endpoint_context_diagnostic after_context;
  std::size_t parent_delete_candidate_id = 0;
  std::size_t parent_insert_candidate_id = 0;
  std::size_t delete_verified_partner_count = 1;
  std::size_t insert_verified_partner_count = 1;
};

struct selection_diagnostics {
  std::vector<candidate_diagnostic> candidates;
  std::vector<type3_pair_diagnostic> type3_pairs;
  std::vector<type2b_group_diagnostic> type2b_groups;
  std::vector<correspondence_diagnostic> correspondences;
};

} // namespace srcmove

#endif
