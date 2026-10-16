#ifndef INCLUDED_SRCMOVE_JSON_WRITER_HPP
#define INCLUDED_SRCMOVE_JSON_WRITER_HPP

#include <map>
#include <ostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#include <vector>

#include "movement_classifier.hpp"
#include "summary.hpp"

namespace srcmove::json {

inline std::string escape(std::string_view s) {
  std::string out;
  out.reserve(s.size() + 8);

  for (char c : s) {
    switch (c) {
    case '"':
      out += "\\\"";
      break;
    case '\\':
      out += "\\\\";
      break;
    case '\n':
      out += "\\n";
      break;
    case '\r':
      out += "\\r";
      break;
    case '\t':
      out += "\\t";
      break;
    default:
      out.push_back(c);
      break;
    }
  }

  return out;
}

inline void write_string(std::ostream &out, std::string_view s) {
  out << "\"" << escape(s) << "\"";
}

inline void write_string_array(std::ostream                   &out,
                               const std::vector<std::string> &arr,
                               std::size_t                     indent) {
  const std::string pad(indent, ' ');
  const std::string item_pad(indent + 2, ' ');

  out << "[\n";

  for (std::size_t i = 0; i < arr.size(); ++i) {
    out << item_pad;
    write_string(out, arr[i]);
    if (i + 1 < arr.size()) {
      out << ",";
    }
    out << "\n";
  }

  out << pad << "]";
}

inline void write_nullable_string(std::ostream &out, std::string_view value) {
  if (value.empty()) out << "null";
  else write_string(out, value);
}

inline std::string_view name_evidence(std::string_view status) {
  if (status == "exact" || status == "unassessed") return "not_assessed";
  if (status == "corroborated" || status == "tentative" || status == "contradicted")
    return status;
  throw std::logic_error("Unknown internal name-evidence status");
}

inline std::string_view correspondence_status(const move_entry &move) {
  if (move.continuing_source_copy) return "copy_source_set";
  if (move.unresolved_exact_residual ||
      move.original.size() != 1 || move.modified.size() != 1)
    return "unresolved_partners";
  return "selected_pair";
}

inline void write_endpoint(std::ostream &out, const result_endpoint &endpoint) {
  out << "{\"candidate_id\": " << endpoint.candidate_id << ", \"revision_file\": ";
  write_nullable_string(out, endpoint.revision_file);
  out << ", \"xpath\": "; write_string(out, endpoint.xpath);
  out << ", \"construct\": "; write_nullable_string(out, endpoint.construct);
  out << ", \"raw_text\": "; write_string(out, endpoint.raw_text);
  out << "}";
}

inline void write_endpoints(std::ostream &out,
                            const std::vector<result_endpoint> &endpoints) {
  out << "[";
  for (std::size_t index = 0; index < endpoints.size(); ++index) {
    if (index) out << ", ";
    write_endpoint(out, endpoints[index]);
  }
  out << "]";
}

inline void write_move_entry(std::ostream &out, const move_entry &move) {
  const auto status = correspondence_status(move);
  out << "    {\n      \"id\": "; write_string(out, move.move_id);
  out << ",\n      \"content_relationship\": "; write_string(out, move.content_relationship);
  out << ",\n      \"original\": "; write_endpoints(out, move.original);
  out << ",\n      \"modified\": "; write_endpoints(out, move.modified);
  out << ",\n      \"correspondence\": {\"status\": "; write_string(out, status);
  out << "},\n      \"name_evidence\": "; write_string(out, name_evidence(move.identity_status));
  out << ",\n      \"location_evidence\": ";
  if (status == "copy_source_set") {
    out << "{\"scope\": \"not_assessed\", \"reason\": \"continuing_source_copy\"}";
  } else if (status == "unresolved_partners") {
    out << "{\"scope\": \"group\", \"status\": \"group_relocation_evidence\"}";
  } else if (!move.has_pair_location) {
    out << "{\"scope\": \"not_assessed\", \"reason\": \"no_classified_pair\"}";
  } else {
    if (!move_eligible(move.pair_location))
      throw std::logic_error("Selected pair lacks eligible retained location evidence");
    out << "{\"scope\": \"pair\", \"classification\": ";
    write_string(out, to_string(move.pair_location.change_kind));
    out << ", \"reason\": "; write_string(out, to_string(move.pair_location.reason));
    out << "}";
  }
  out << ",\n      \"selection\": {\"matching_weight_milli\": " << move.confidence_milli
      << ", \"utility\": " << move.selection_utility
      << ", \"matched_units\": " << move.matched_units << ", \"reason\": ";
  write_string(out, move.selection_reason);
  out << "}\n    }";
}

inline void write_sequence_endpoint(std::ostream &out,
                                     const move_sequence_endpoint &endpoint) {
  out << "{\"revision_file\": "; write_string(out, endpoint.revision_file);
  out << ", \"parent_id\": "; write_string(out, endpoint.parent_id);
  out << ", \"first_child_ordinal\": " << endpoint.first_child_ordinal
      << ", \"last_child_ordinal\": " << endpoint.last_child_ordinal << "}";
}

inline void write_output_item(std::ostream &out, const reported_move_entry &item,
                               const move_sequence *sequence) {
  out << "    {\"id\": "; write_string(out, item.move_id);
  out << ", \"kind\": "; write_string(out, item.report_kind);
  out << ", \"member_group_ids\": "; write_string_array(out, item.member_move_ids, 4);
  if (item.report_kind == "sequence_move_group") {
    if (sequence == nullptr || sequence->member_move_ids != item.member_move_ids)
      throw std::logic_error("Sequence output item lacks matching retained context");
    out << ", \"sequence\": {\"policy\": \"ordered_adjacent_v1\", \"original\": ";
    write_sequence_endpoint(out, sequence->from);
    out << ", \"modified\": "; write_sequence_endpoint(out, sequence->to);
    out << "}";
  } else if (item.report_kind != "atomic_move_group") {
    throw std::logic_error("Unknown output-item kind");
  }
  out << "}";
}

using selected_pair_key = std::tuple<std::size_t, std::size_t, std::string>;

struct result_links {
  std::map<std::size_t, const move_entry *> owners;
  std::map<selected_pair_key, const move_entry *> pairs;

  explicit result_links(const summary &summ) {
    for (const auto &move : summ.moves) {
      for (const auto *endpoints : {&move.original, &move.modified}) {
        for (const auto &endpoint : *endpoints)
          if (!owners.emplace(endpoint.candidate_id, &move).second)
            throw std::logic_error("Selected candidate has multiple owners");
      }
      if (correspondence_status(move) == "selected_pair")
        pairs.emplace(selected_pair_key{move.original.front().candidate_id,
                      move.modified.front().candidate_id, move.content_relationship}, &move);
    }
  }

  const move_entry *pair(std::size_t original, std::size_t modified,
                          const std::string &relationship) const {
    const auto found = pairs.find({original, modified, relationship});
    return found == pairs.end() ? nullptr : found->second;
  }
};

inline void write_context(std::ostream &out,
                           const endpoint_context_diagnostic &context) {
  out << "{\"revision_file\": "; write_nullable_string(out, context.revision_file);
  out << ", \"semantic_container_id\": "; write_nullable_string(out, context.semantic_container_id);
  out << ", \"semantic_container_label\": "; write_nullable_string(out, context.semantic_container_label);
  out << ", \"previous_common_anchor_id\": "; write_nullable_string(out, context.previous_common_anchor_id);
  out << ", \"next_common_anchor_id\": "; write_nullable_string(out, context.next_common_anchor_id);
  out << ", \"meaningful_ancestors\": "; write_string_array(out, context.meaningful_ancestors, 8);
  out << ", \"ancestor_summary_interpretable\": " << (context.ancestor_summary_interpretable ? "true" : "false");
  out << ", \"structural_region_id\": "; write_nullable_string(out, context.structural_region_id);
  out << ", \"structural_region_mapped\": " << (context.structural_region_mapped ? "true" : "false")
      << ", \"common_sibling_prefix_count\": " << context.common_sibling_prefix_count
      << ", \"common_sibling_suffix_begin\": " << context.common_sibling_suffix_begin;
  out << ", \"anchor_region_id\": "; write_nullable_string(out, context.anchor_region_id);
  out << "}";
}

inline void write_diagnostic_location(std::ostream &out,
                                      const correspondence_diagnostic &item) {
  out << "{\"scope\": \"pair\", \"classification\": "; write_string(out, item.shadow_change);
  out << ", \"reason\": "; write_string(out, item.classification_reason);
  out << ", \"observations\": {\"file\": "; write_string(out, item.file_observation);
  out << ", \"semantic_container\": "; write_string(out, item.semantic_container_observation);
  out << ", \"anchor_interval\": "; write_string(out, item.anchor_interval_observation);
  out << ", \"relative_order\": "; write_string(out, item.relative_order_observation);
  out << ", \"ancestor\": "; write_string(out, item.ancestor_observation);
  out << "}, \"carried_by_parent\": " << (item.carried_by_parent ? "true" : "false")
      << ", \"parent_pair\": ";
  if (item.carried_by_parent)
    out << "{\"original_candidate_id\": " << item.parent_delete_candidate_id
        << ", \"modified_candidate_id\": " << item.parent_insert_candidate_id << "}";
  else out << "null";
  out << "}";
}

inline void write_diagnostic_selection(std::ostream &out, std::string_view selected_status,
                                       std::string_view unselected_status,
                                       const move_entry *selected, bool reason = false) {
  out << "{\"status\": ";
  write_string(out, selected ? selected_status : unselected_status);
  out << ", \"selected_group_id\": ";
  if (selected) write_string(out, selected->move_id);
  else out << "null";
  if (reason) out << ", \"reason\": null";
  out << "}";
}

inline void write_candidate_ids(std::ostream &out, const std::vector<std::size_t> &ids) {
  out << "[";
  for (std::size_t index = 0; index < ids.size(); ++index) {
    if (index) out << ", ";
    out << ids[index];
  }
  out << "]";
}

inline void write_selection_diagnostics(std::ostream &out, const summary &summ,
                                         const result_links &links) {
  const auto &diagnostics = summ.diagnostics;
  out << "  \"diagnostics\": {\n    \"schema_version\": 5,\n"
      << "    \"candidate_counts\": {\"registered\": " << summ.registered_candidate_count
      << ", \"active\": " << summ.active_candidate_count << "},\n    \"candidates\": [\n";
  for (std::size_t index = 0; index < diagnostics.candidates.size(); ++index) {
    const auto &candidate = diagnostics.candidates[index];
    const auto owner = links.owners.find(candidate.candidate_id);
    out << "      {\"candidate_id\": " << candidate.candidate_id << ", \"revision\": ";
    if (candidate.side == "delete") write_string(out, "original");
    else if (candidate.side == "insert") write_string(out, "modified");
    else throw std::logic_error("Unknown diagnostic candidate side");
    out << ", \"role\": "; write_string(out, candidate.role);
    out << ", \"selected_group_id\": ";
    if (owner != links.owners.end()) write_string(out, owner->second->move_id);
    else out << "null";
    out << ", \"endpoint\": ";
    if (owner != links.owners.end()) out << "null";
    else {
      out << "{\"candidate_id\": " << candidate.candidate_id << ", \"revision_file\": ";
      write_nullable_string(out, candidate.revision_file);
      out << ", \"xpath\": "; write_string(out, candidate.xpath);
      out << ", \"construct\": "; write_nullable_string(out, candidate.construct);
      out << ", \"raw_text\": "; write_string(out, candidate.raw_text);
      out << "}";
    }
    out << ", \"type3_eligible\": " << (candidate.type3_eligible ? "true" : "false")
        << ", \"line_units\": " << candidate.line_units
        << ", \"token_units\": " << candidate.token_units << "}";
    if (index + 1 < diagnostics.candidates.size()) out << ",";
    out << "\n";
  }
  out << "    ],\n    \"correspondences\": [\n";
  for (std::size_t index = 0; index < diagnostics.correspondences.size(); ++index) {
    const auto &item = diagnostics.correspondences[index];
    const auto *selected = links.pair(item.delete_candidate_id, item.insert_candidate_id,
                                      item.correspondence_kind);
    out << "      {\"id\": "; write_string(out, "correspondence:" + std::to_string(index));
    out << ", \"original_candidate_id\": " << item.delete_candidate_id
        << ", \"modified_candidate_id\": " << item.insert_candidate_id
        << ", \"content_relationship\": "; write_string(out, item.correspondence_kind);
    out << ", \"name_evidence\": "; write_string(out, name_evidence(item.identity_status));
    out << ", \"location\": "; write_diagnostic_location(out, item);
    out << ", \"original_context\": "; write_context(out, item.before_context);
    out << ", \"modified_context\": "; write_context(out, item.after_context);
    out << ", \"verified_partner_counts\": ";
    if (item.correspondence_kind == "type3")
      out << "{\"original\": " << item.delete_verified_partner_count
          << ", \"modified\": " << item.insert_verified_partner_count << "}";
    else out << "null";
    out << ", \"selection\": ";
    write_diagnostic_selection(out, "selected_pair", "not_selected_pair", selected);
    out << "}";
    if (index + 1 < diagnostics.correspondences.size()) out << ",";
    out << "\n";
  }
  out << "    ],\n    \"type3_comparisons\": [\n";
  for (std::size_t index = 0; index < diagnostics.type3_pairs.size(); ++index) {
    const auto &pair = diagnostics.type3_pairs[index];
    const bool skipped = pair.outcome == "ambiguous_type2c";
    const bool verified = pair.outcome == "selected" || pair.outcome == "selection_rejected";
    if (!skipped && !verified && pair.outcome != "below_threshold")
      throw std::logic_error("Unknown Type-3 diagnostic outcome");
    const auto *selected = links.pair(pair.del_candidate_id, pair.ins_candidate_id, "type3");
    if ((pair.outcome == "selected") != (selected != nullptr))
      throw std::logic_error("Type-3 recorded selection differs from selected evidence");
    out << "      {\"id\": "; write_string(out, "type3:" + std::to_string(index));
    out << ", \"original_candidate_id\": " << pair.del_candidate_id
        << ", \"modified_candidate_id\": " << pair.ins_candidate_id
        << ", \"verification\": {\"status\": ";
    write_string(out, skipped ? "not_evaluated" : verified ? "verified" : "below_threshold");
    out << ", \"reason\": ";
    if (skipped) write_string(out, "ambiguous_type2c");
    else out << "null";
    out << ", \"lines\": {\"common\": ";
    if (skipped) out << "null"; else out << pair.common_lines;
    out << ", \"maximum\": " << pair.maximum_lines << "}, \"tokens\": {\"common\": ";
    if (skipped) out << "null"; else out << pair.common_tokens;
    out << ", \"maximum\": " << pair.maximum_tokens << "}}, \"selection\": ";
    write_diagnostic_selection(out, "selected", verified ? "not_selected" : "not_applicable",
                                selected, true);
    out << "}";
    if (index + 1 < diagnostics.type3_pairs.size()) out << ",";
    out << "\n";
  }
  out << "    ],\n    \"type2b_groups\": [\n";
  for (std::size_t index = 0; index < diagnostics.type2b_groups.size(); ++index) {
    const auto &group = diagnostics.type2b_groups[index];
    out << "      {\"id\": "; write_string(out, "type2b:" + std::to_string(index));
    out << ", \"content_relationship\": \"type2b\", \"observation_only\": true"
        << ", \"original_candidate_ids\": "; write_candidate_ids(out, group.delete_candidate_ids);
    out << ", \"modified_candidate_ids\": "; write_candidate_ids(out, group.insert_candidate_ids);
    out << ", \"blind_only_pair_count\": " << group.blind_only_pair_count << ", \"location\": ";
    if (group.location_change.empty()) out << "null";
    else {
      out << "{\"classification\": "; write_string(out, group.location_change);
      out << ", \"reason\": "; write_string(out, group.location_reason);
      out << "}";
    }
    out << "}";
    if (index + 1 < diagnostics.type2b_groups.size()) out << ",";
    out << "\n";
  }
  out << "    ]\n  }";
}

inline void write_relationship_counts(std::ostream &out,
                                       const content_relationship_counts &counts) {
  out << "{\"type1\": " << counts.type1 << ", \"type2c\": " << counts.type2c
      << ", \"type3\": " << counts.type3 << "}";
}

inline void write_summary(std::ostream &out, const summary &summ) {
  out << "{\n  \"results_schema_version\": " << results_schema_version
      << ",\n  \"summary\": {\"output_item_count\": " << summ.reported_moves.size()
      << ", \"atomic_move_group_count\": " << summ.moves.size()
      << ", \"sequence_move_group_count\": " << summ.move_sequences.size()
      << ", \"pair_capacity\": " << summ.move_pair_count
      << ", \"endpoint_count\": " << summ.annotated_region_count
      << ", \"atomic_content_relationships\": ";
  write_relationship_counts(out, summ.content_relationships);
  out << ", \"output_content_relationships\": ";
  write_relationship_counts(out, summ.reported_content_relationships);
  out << "},\n  \"output_items\": [\n";
  std::map<std::string, const move_sequence *> sequences;
  for (const auto &sequence : summ.move_sequences) {
    if (sequence.member_move_ids.empty())
      throw std::logic_error("Empty retained sequence");
    sequences.emplace(sequence.member_move_ids.front(), &sequence);
  }
  for (std::size_t index = 0; index < summ.reported_moves.size(); ++index) {
    const auto &item = summ.reported_moves[index];
    const auto sequence = item.member_move_ids.empty() ? sequences.end()
                         : sequences.find(item.member_move_ids.front());
    write_output_item(out, item, sequence == sequences.end() ? nullptr : sequence->second);
    if (index + 1 < summ.reported_moves.size()) out << ",";
    out << "\n";
  }
  out << "  ],\n  \"atomic_move_groups\": [\n";
  for (std::size_t index = 0; index < summ.moves.size(); ++index) {
    write_move_entry(out, summ.moves[index]);
    if (index + 1 < summ.moves.size()) out << ",";
    out << "\n";
  }
  out << "  ],\n  \"configuration\": {\"min_granularity\": ";
  write_string(out, summ.min_granularity);
  out << ", \"sequence_policy\": \"ordered_adjacent_v1\"},\n"
      << "  \"pipeline_statistics\": {\"srcdiff_region_count\": " << summ.regions_total
      << ", \"grouped_candidate_entry_count\": " << summ.candidates_total
      << ", \"processing_group_count\": " << summ.groups_total
      << ", \"processing_group_kinds\": {\"move_1_to_1\": " << summ.group_kinds.move_1_to_1
      << ", \"moves_many\": " << summ.group_kinds.moves_many
      << ", \"delete_only\": " << summ.group_kinds.delete_only
      << ", \"insert_only\": " << summ.group_kinds.insert_only
      << ", \"copy_or_repeat\": " << summ.group_kinds.copy_or_repeat
      << ", \"ambiguous\": " << summ.group_kinds.ambiguous << "}}";
  out << ",\n  \"xpath_context\": {\"document\": \"input_srcdiff\", "
      << "\"convention\": \"srcreader_file_units_v1\", \"namespaces\": {";
  bool first_namespace = true;
  for (const auto &[prefix, uri] : summ.xpath_namespaces) {
    if (!first_namespace) out << ", ";
    first_namespace = false;
    write_string(out, prefix); out << ": "; write_string(out, uri);
  }
  out << "}}";
  if (summ.diagnostics_enabled) {
    out << ",\n";
    write_selection_diagnostics(out, summ, result_links(summ));
  }
  out << "\n}\n";
}

} // namespace srcmove::json

#endif
