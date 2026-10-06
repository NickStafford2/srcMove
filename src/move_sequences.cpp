// SPDX-License-Identifier: GPL-3.0-only
#include "move_sequences.hpp"

#include <algorithm>
#include <tuple>
#include <unordered_map>
#include <unordered_set>

#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_groups.hpp"
#include "summary.hpp"

namespace srcmove {
namespace {

struct sequence_link {
  const move_entry *move;
  const move_candidate *from;
  const move_candidate *to;
};

bool reliable_child(const move_candidate &candidate) {
  return candidate.role == move_candidate::Role::structural_child &&
         candidate.sequence_context_reliable &&
         !candidate.sequence_parent_id.empty() &&
         candidate.sequence_sibling_ordinal != 0 &&
         !candidate.location.revision_file.empty() && !candidate.xpath.empty() &&
         candidate.start_idx < candidate.end_idx;
}

auto partition_key(const sequence_link &link) {
  return std::tie(link.from->location.revision_file,
                  link.from->sequence_parent_id,
                  link.to->location.revision_file,
                  link.to->sequence_parent_id);
}

bool consecutive(const sequence_link &previous, const sequence_link &next) {
  return partition_key(previous) == partition_key(next) &&
         next.from->sequence_sibling_ordinal >
             previous.from->sequence_sibling_ordinal &&
         next.from->sequence_sibling_ordinal -
                 previous.from->sequence_sibling_ordinal == 1 &&
         next.to->sequence_sibling_ordinal > previous.to->sequence_sibling_ordinal &&
         next.to->sequence_sibling_ordinal -
                 previous.to->sequence_sibling_ordinal == 1 &&
         previous.from->end_idx < next.from->start_idx &&
         previous.to->end_idx < next.to->start_idx;
}

void append_endpoint(move_sequence_endpoint &endpoint,
                     const move_candidate &candidate) {
  if (endpoint.member_xpaths.empty()) {
    endpoint.revision_file = candidate.location.revision_file;
    endpoint.parent_id = candidate.sequence_parent_id;
    endpoint.first_child_ordinal = candidate.sequence_sibling_ordinal;
  }
  endpoint.last_child_ordinal = candidate.sequence_sibling_ordinal;
  endpoint.member_xpaths.push_back(candidate.xpath);
}

} // namespace

std::vector<move_sequence>
build_move_sequences(const candidate_registry &registry,
                     const content_groups &groups,
                     const std::vector<move_entry> &moves) {
  // Only selected one-to-one groups supply endpoint pairs. In particular, a
  // repeated exact group never becomes an inferred set of ordered partners.
  std::unordered_map<std::string, const content_group *> by_from_xpath;
  by_from_xpath.reserve(groups.group_count());
  for (const content_group &group : groups.groups()) {
    if (group.match != match_kind::type1 ||
        group.kind != group_kind::move_1_to_1 ||
        group.del_count() != 1 || group.ins_count() != 1) {
      continue;
    }
    const auto &from = registry.candidate(groups.delete_ids(group)[0]);
    const auto &to = registry.candidate(groups.insert_ids(group)[0]);
    if (!reliable_child(from) || !reliable_child(to)) {
      continue;
    }
    const auto inserted = by_from_xpath.emplace(from.xpath, &group);
    // Duplicate archive paths or aliases do not establish unique context.
    if (!inserted.second) {
      inserted.first->second = nullptr;
    }
  }

  std::vector<sequence_link> links;
  links.reserve(moves.size());
  for (const move_entry &move : moves) {
    if (move.content_relationship != "type1" || move.from_xpaths.size() != 1 ||
        move.to_xpaths.size() != 1 || move.move_id.empty()) {
      continue;
    }
    const auto found = by_from_xpath.find(move.from_xpaths[0]);
    if (found == by_from_xpath.end() || found->second == nullptr) {
      continue;
    }
    const content_group &group = *found->second;
    const auto &from = registry.candidate(groups.delete_ids(group)[0]);
    const auto &to = registry.candidate(groups.insert_ids(group)[0]);
    if (to.xpath == move.to_xpaths[0]) {
      links.push_back(sequence_link{&move, &from, &to});
    }
  }

  std::sort(links.begin(), links.end(),
            [](const sequence_link &left, const sequence_link &right) {
              if (partition_key(left) != partition_key(right)) {
                return partition_key(left) < partition_key(right);
              }
              return std::tie(left.from->sequence_sibling_ordinal,
                              left.to->sequence_sibling_ordinal,
                              left.move->move_id) <
                     std::tie(right.from->sequence_sibling_ordinal,
                              right.to->sequence_sibling_ordinal,
                              right.move->move_id);
            });

  std::vector<move_sequence> sequences;
  for (std::size_t begin = 0; begin < links.size();) {
    std::size_t end = begin + 1;
    while (end < links.size() && consecutive(links[end - 1], links[end])) {
      ++end;
    }
    if (end - begin >= 2) {
      move_sequence sequence;
      // Same identity scope as atomic IDs: stable within this result's members.
      // No UUID calls are added, preserving original annotation identifiers.
      sequence.sequence_id = "sequence:" + links[begin].move->move_id;
      sequence.member_move_ids.reserve(end - begin);
      sequence.from.member_xpaths.reserve(end - begin);
      sequence.to.member_xpaths.reserve(end - begin);
      for (std::size_t index = begin; index < end; ++index) {
        sequence.member_move_ids.push_back(links[index].move->move_id);
        append_endpoint(sequence.from, *links[index].from);
        append_endpoint(sequence.to, *links[index].to);
      }
      sequences.push_back(std::move(sequence));
    }
    begin = end;
  }
  return sequences;
}

std::vector<reported_move_entry>
build_reported_moves(const std::vector<move_entry> &moves,
                     const std::vector<move_sequence> &sequences) {
  std::unordered_map<std::string, const move_entry *> by_id;
  std::unordered_map<std::string, const move_sequence *> sequence_by_member;
  by_id.reserve(moves.size());
  sequence_by_member.reserve(moves.size());
  for (const auto &move : moves) by_id.emplace(move.move_id, &move);
  for (const auto &sequence : sequences) {
    for (const auto &id : sequence.member_move_ids) {
      sequence_by_member.emplace(id, &sequence);
    }
  }

  std::vector<reported_move_entry> reports;
  reports.reserve(moves.size());
  std::unordered_set<std::string> emitted_sequences;
  for (const auto &move : moves) {
    const auto found = sequence_by_member.find(move.move_id);
    const move_sequence *sequence = found == sequence_by_member.end()
                                        ? nullptr : found->second;
    if (sequence && !emitted_sequences.insert(sequence->sequence_id).second) {
      continue;
    }
    reported_move_entry report;
    report.move_id = sequence ? sequence->sequence_id : move.move_id;
    report.report_kind = sequence ? "ordered_sequence" : "atomic";
    report.content_relationship = move.content_relationship;
    report.identity_status = move.identity_status;
    report.identity_reason = move.identity_reason;
    report.member_move_ids = sequence ? sequence->member_move_ids
                                     : std::vector<std::string>{move.move_id};
    for (const auto &id : report.member_move_ids) {
      const auto &member = *by_id.at(id);
      report.from_xpaths.insert(report.from_xpaths.end(), member.from_xpaths.begin(),
                               member.from_xpaths.end());
      report.to_xpaths.insert(report.to_xpaths.end(), member.to_xpaths.begin(),
                             member.to_xpaths.end());
      report.from_raw_texts.insert(report.from_raw_texts.end(), member.from_raw_texts.begin(),
                                  member.from_raw_texts.end());
      report.to_raw_texts.insert(report.to_raw_texts.end(), member.to_raw_texts.begin(),
                                member.to_raw_texts.end());
    }
    reports.push_back(std::move(report));
  }
  return reports;
}

} // namespace srcmove
