#ifndef INCLUDED_SRCMOVE_JSON_WRITER_HPP
#define INCLUDED_SRCMOVE_JSON_WRITER_HPP

#include <ostream>
#include <string>
#include <string_view>
#include <vector>

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

inline void write_move_entry(std::ostream     &out,
                             const move_entry &m,
                             std::size_t       indent = 4) {
  const std::string pad(indent, ' ');
  const std::string field_pad(indent + 2, ' ');

  out << pad << "{\n";
  out << field_pad << "\"move_id\": \"" << m.move_id << "\",\n";
  out << field_pad << "\"content_relationship\": ";
  write_string(out, m.content_relationship);
  out << ",\n";
  out << field_pad << "\"confidence_milli\": " << m.confidence_milli
      << ",\n";
  out << field_pad << "\"selection_utility\": " << m.selection_utility
      << ",\n";
  out << field_pad << "\"matched_units\": " << m.matched_units << ",\n";
  out << field_pad << "\"selection_reason\": ";
  write_string(out, m.selection_reason);
  out << ",\n";

  out << field_pad << "\"from_xpaths\": ";
  write_string_array(out, m.from_xpaths, indent + 2);
  out << ",\n";

  out << field_pad << "\"to_xpaths\": ";
  write_string_array(out, m.to_xpaths, indent + 2);
  out << ",\n";

  out << field_pad << "\"from_raw_texts\": ";
  write_string_array(out, m.from_raw_texts, indent + 2);
  out << ",\n";

  out << field_pad << "\"to_raw_texts\": ";
  write_string_array(out, m.to_raw_texts, indent + 2);
  out << "\n";

  out << pad << "}";
}

inline void write_selection_diagnostics(std::ostream &out,
                                        const selection_diagnostics &diagnostics) {
  out << "  \"diagnostics\": {\n";
  out << "    \"schema_version\": 4,\n";
  out << "    \"candidates\": [\n";
  for (std::size_t index = 0; index < diagnostics.candidates.size(); ++index) {
    const candidate_diagnostic &candidate = diagnostics.candidates[index];
    out << "      {\n";
    out << "        \"candidate_id\": " << candidate.candidate_id << ",\n";
    out << "        \"side\": "; write_string(out, candidate.side); out << ",\n";
    out << "        \"filename\": "; write_string(out, candidate.filename); out << ",\n";
    out << "        \"xpath\": "; write_string(out, candidate.xpath); out << ",\n";
    out << "        \"construct\": "; write_string(out, candidate.construct); out << ",\n";
    out << "        \"role\": "; write_string(out, candidate.role); out << ",\n";
    out << "        \"raw_text\": "; write_string(out, candidate.raw_text); out << ",\n";
    out << "        \"type3_eligible\": "
        << (candidate.type3_eligible ? "true" : "false") << ",\n";
    out << "        \"line_units\": " << candidate.line_units << ",\n";
    out << "        \"token_units\": " << candidate.token_units << "\n";
    out << "      }";
    if (index + 1 < diagnostics.candidates.size()) out << ",";
    out << "\n";
  }
  out << "    ],\n";
  out << "    \"type2b_groups\": [\n";
  for (std::size_t index = 0; index < diagnostics.type2b_groups.size(); ++index) {
    const auto &group = diagnostics.type2b_groups[index];
    const auto write_ids = [&](const std::vector<std::size_t> &ids) {
      out << "[";
      for (std::size_t i = 0; i < ids.size(); ++i) {
        if (i != 0) out << ", ";
        out << ids[i];
      }
      out << "]";
    };
    out << "      {\n        \"correspondence_kind\": \"type2b\",\n";
    out << "        \"observation_only\": true,\n";
    out << "        \"cardinality\": ";
    write_string(out, group.delete_candidate_ids.size() == 1 &&
                          group.insert_candidate_ids.size() == 1
                          ? "one_to_one" : "ambiguous");
    out << ",\n        \"delete_candidate_ids\": ";
    write_ids(group.delete_candidate_ids);
    out << ",\n        \"insert_candidate_ids\": ";
    write_ids(group.insert_candidate_ids);
    out << ",\n        \"blind_only_pair_count\": " << group.blind_only_pair_count;
    if (!group.location_change.empty()) {
      out << ",\n        \"location_change\": ";
      write_string(out, group.location_change);
      out << ",\n        \"location_reason\": ";
      write_string(out, group.location_reason);
    }
    out << "\n      }";
    if (index + 1 < diagnostics.type2b_groups.size()) out << ",";
    out << "\n";
  }
  out << "    ],\n";
  out << "    \"type3_pairs\": [\n";
  for (std::size_t index = 0; index < diagnostics.type3_pairs.size(); ++index) {
    const type3_pair_diagnostic &pair = diagnostics.type3_pairs[index];
    out << "      {\n";
    out << "        \"delete_candidate_id\": " << pair.del_candidate_id << ",\n";
    out << "        \"insert_candidate_id\": " << pair.ins_candidate_id << ",\n";
    out << "        \"outcome\": "; write_string(out, pair.outcome); out << ",\n";
    out << "        \"common_lines\": " << pair.common_lines << ",\n";
    out << "        \"maximum_lines\": " << pair.maximum_lines << ",\n";
    out << "        \"common_tokens\": " << pair.common_tokens << ",\n";
    out << "        \"maximum_tokens\": " << pair.maximum_tokens << "\n";
    out << "      }";
    if (index + 1 < diagnostics.type3_pairs.size()) out << ",";
    out << "\n";
  }
  out << "    ],\n";
  out << "    \"correspondences\": [\n";
  for (std::size_t index = 0; index < diagnostics.correspondences.size();
       ++index) {
    const correspondence_diagnostic &item = diagnostics.correspondences[index];
    const auto write_context = [&](const endpoint_context_diagnostic &context,
                                   std::size_t indent) {
      const std::string pad(indent, ' ');
      const std::string field_pad(indent + 2, ' ');
      out << "{\n";
      out << field_pad << "\"revision_file\": ";
      write_string(out, context.revision_file); out << ",\n";
      out << field_pad << "\"semantic_container_id\": ";
      write_string(out, context.semantic_container_id); out << ",\n";
      out << field_pad << "\"semantic_container_label\": ";
      write_string(out, context.semantic_container_label); out << ",\n";
      out << field_pad << "\"previous_common_anchor_id\": ";
      write_string(out, context.previous_common_anchor_id); out << ",\n";
      out << field_pad << "\"next_common_anchor_id\": ";
      write_string(out, context.next_common_anchor_id); out << ",\n";
      out << field_pad << "\"meaningful_ancestors\": ";
      write_string_array(out, context.meaningful_ancestors, indent + 2);
      out << ",\n";
      out << field_pad << "\"ancestor_summary_interpretable\": "
          << (context.ancestor_summary_interpretable ? "true" : "false")
          << "\n" << pad << "}";
    };
    out << "      {\n";
    out << "        \"delete_candidate_id\": " << item.delete_candidate_id
        << ",\n";
    out << "        \"insert_candidate_id\": " << item.insert_candidate_id
        << ",\n";
    out << "        \"correspondence_kind\": ";
    write_string(out, item.correspondence_kind); out << ",\n";
    out << "        \"cardinality\": ";
    write_string(out, item.cardinality); out << ",\n";
    if (item.correspondence_kind == "type3") {
      out << "        \"delete_verified_partner_count\": "
          << item.delete_verified_partner_count << ",\n";
      out << "        \"insert_verified_partner_count\": "
          << item.insert_verified_partner_count << ",\n";
    }
    out << "        \"current_result\": ";
    write_string(out, item.current_result); out << ",\n";
    out << "        \"shadow_change\": ";
    write_string(out, item.shadow_change); out << ",\n";
    out << "        \"classification_reason\": ";
    write_string(out, item.classification_reason); out << ",\n";
    if (!item.identity_reason.empty()) {
      out << "        \"identity_reason\": ";
      write_string(out, item.identity_reason); out << ",\n";
    }
    out << "        \"file_observation\": ";
    write_string(out, item.file_observation); out << ",\n";
    out << "        \"semantic_container_observation\": ";
    write_string(out, item.semantic_container_observation); out << ",\n";
    out << "        \"anchor_interval_observation\": ";
    write_string(out, item.anchor_interval_observation); out << ",\n";
    out << "        \"relative_order_observation\": ";
    write_string(out, item.relative_order_observation); out << ",\n";
    out << "        \"ancestor_observation\": ";
    write_string(out, item.ancestor_observation); out << ",\n";
    out << "        \"carried_by_parent\": "
        << (item.carried_by_parent ? "true" : "false") << ",\n";
    out << "        \"parent_delete_candidate_id\": ";
    if (item.carried_by_parent) out << item.parent_delete_candidate_id;
    else out << "null";
    out << ",\n";
    out << "        \"parent_insert_candidate_id\": ";
    if (item.carried_by_parent) out << item.parent_insert_candidate_id;
    else out << "null";
    out << ",\n";
    out << "        \"before_context\": ";
    write_context(item.before_context, 8); out << ",\n";
    out << "        \"after_context\": ";
    write_context(item.after_context, 8); out << "\n";
    out << "      }";
    if (index + 1 < diagnostics.correspondences.size()) out << ",";
    out << "\n";
  }
  out << "    ]\n";
  out << "  }\n";
}

inline void write_sequence_endpoint(std::ostream &out,
                                    const move_sequence_endpoint &endpoint,
                                    std::size_t indent) {
  const std::string pad(indent, ' ');
  const std::string field_pad(indent + 2, ' ');
  out << "{\n" << field_pad << "\"revision_file\": ";
  write_string(out, endpoint.revision_file);
  out << ",\n" << field_pad << "\"parent_id\": ";
  write_string(out, endpoint.parent_id);
  out << ",\n" << field_pad << "\"first_child_ordinal\": "
      << endpoint.first_child_ordinal;
  out << ",\n" << field_pad << "\"last_child_ordinal\": "
      << endpoint.last_child_ordinal;
  out << ",\n" << field_pad << "\"member_xpaths\": ";
  write_string_array(out, endpoint.member_xpaths, indent + 2);
  out << "\n" << pad << "}";
}

inline void write_move_sequence(std::ostream &out, const move_sequence &sequence,
                                std::size_t indent = 4) {
  const std::string pad(indent, ' ');
  const std::string field_pad(indent + 2, ' ');
  out << pad << "{\n" << field_pad << "\"sequence_id\": ";
  write_string(out, sequence.sequence_id);
  out << ",\n" << field_pad << "\"content_relationship\": \"type1\",\n";
  out << field_pad << "\"policy\": \"ordered_adjacent_v1\",\n";
  out << field_pad << "\"member_move_ids\": ";
  write_string_array(out, sequence.member_move_ids, indent + 2);
  out << ",\n" << field_pad << "\"from\": ";
  write_sequence_endpoint(out, sequence.from, indent + 2);
  out << ",\n" << field_pad << "\"to\": ";
  write_sequence_endpoint(out, sequence.to, indent + 2);
  out << "\n" << pad << "}";
}

inline void write_reported_move(std::ostream &out, const reported_move_entry &report) {
  out << "    {\n      \"move_id\": ";
  write_string(out, report.move_id);
  out << ",\n      \"report_kind\": ";
  write_string(out, report.report_kind);
  out << ",\n      \"content_relationship\": ";
  write_string(out, report.content_relationship);
  out << ",\n      \"member_move_ids\": ";
  write_string_array(out, report.member_move_ids, 6);
  out << ",\n      \"from_xpaths\": ";
  write_string_array(out, report.from_xpaths, 6);
  out << ",\n      \"to_xpaths\": ";
  write_string_array(out, report.to_xpaths, 6);
  out << ",\n      \"from_raw_texts\": ";
  write_string_array(out, report.from_raw_texts, 6);
  out << ",\n      \"to_raw_texts\": ";
  write_string_array(out, report.to_raw_texts, 6);
  out << "\n    }";
}

inline void write_summary(std::ostream &out, const summary &summ) {
  out << "{\n";
  out << "  \"results_schema_version\": " << results_schema_version << ",\n";
  out << "  \"move_count\": " << summ.move_count << ",\n";
  out << "  \"move_group_count\": " << summ.move_group_count << ",\n";
  out << "  \"move_pair_count\": " << summ.move_pair_count << ",\n";
  out << "  \"moves\": [\n";

  for (std::size_t i = 0; i < summ.moves.size(); ++i) {
    write_move_entry(out, summ.moves[i], 4);
    if (i + 1 < summ.moves.size())
      out << ",";
    out << "\n";
  }

  out << "  ],\n";
  out << "  \"reported_move_count\": " << summ.reported_move_count << ",\n";
  out << "  \"reported_content_relationships\": {\n";
  out << "    \"type1\": " << summ.reported_content_relationships.type1 << ",\n";
  out << "    \"type2c\": " << summ.reported_content_relationships.type2c << ",\n";
  out << "    \"type3\": " << summ.reported_content_relationships.type3 << "\n  },\n";
  out << "  \"reported_moves\": [\n";
  for (std::size_t i = 0; i < summ.reported_moves.size(); ++i) {
    write_reported_move(out, summ.reported_moves[i]);
    if (i + 1 < summ.reported_moves.size()) out << ",";
    out << "\n";
  }
  out << "  ],\n";
  out << "  \"sequence_cluster_count\": " << summ.sequence_cluster_count << ",\n";
  out << "  \"sequence_reporting_unit_count\": "
      << summ.sequence_reporting_unit_count << ",\n";
  out << "  \"move_sequences\": [\n";
  for (std::size_t i = 0; i < summ.move_sequences.size(); ++i) {
    write_move_sequence(out, summ.move_sequences[i]);
    if (i + 1 < summ.move_sequences.size()) out << ",";
    out << "\n";
  }
  out << "  ],\n";
  out << "  \"annotated_regions\": " << summ.annotated_regions << ",\n";
  out << "  \"annotated_region_count\": " << summ.annotated_region_count
      << ",\n";
  out << "  \"regions_total\": " << summ.regions_total << ",\n";
  out << "  \"candidates_total\": " << summ.candidates_total << ",\n";
  out << "  \"groups_total\": " << summ.groups_total << ",\n";
  out << "  \"group_kinds\": {\n";
  out << "    \"move_1_to_1\": " << summ.group_kinds.move_1_to_1 << ",\n";
  out << "    \"moves_many\": " << summ.group_kinds.moves_many << ",\n";
  out << "    \"delete_only\": " << summ.group_kinds.delete_only << ",\n";
  out << "    \"insert_only\": " << summ.group_kinds.insert_only << ",\n";
  out << "    \"copy_or_repeat\": " << summ.group_kinds.copy_or_repeat << ",\n";
  out << "    \"ambiguous\": " << summ.group_kinds.ambiguous << "\n";
  out << "  },\n";
  out << "  \"content_relationships\": {\n";
  out << "    \"type1\": " << summ.content_relationships.type1 << ",\n";
  out << "    \"type2c\": " << summ.content_relationships.type2c << ",\n";
  out << "    \"type3\": " << summ.content_relationships.type3 << "\n";
  out << "  }";
  if (summ.diagnostics_enabled) {
    out << ",\n";
    write_selection_diagnostics(out, summ.diagnostics);
  } else {
    out << "\n";
  }
  out << "}\n";
}

} // namespace srcmove::json

#endif
