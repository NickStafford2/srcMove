// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file content_group_builder.cpp
 */

#include "content_group_builder.hpp"
#include "move_candidate.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_groups.hpp"
#include "move_registry/group_selection.hpp"
#include "move_registry/sequence_similarity.hpp"
#include "move_registry/selection_policy.hpp"
#include "profile.hpp"
#include "movement_classifier.hpp"

#include <algorithm>
#include <cassert>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <numeric>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace srcmove {

namespace {

struct grouping_profile_stats {
  std::uint64_t exact_groups_built          = 0;
  std::uint64_t type1_groups_selected       = 0;
  std::uint64_t type1_policy_rejected       = 0;
  std::uint64_t type2_groups_built          = 0;
  std::uint64_t type2_groups_selected       = 0;
  std::uint64_t type3_delete_candidates     = 0;
  std::uint64_t type3_insert_candidates     = 0;
  std::uint64_t type3_shortlist_entries     = 0;
  std::uint64_t type3_pairs_considered      = 0;
  std::uint64_t type3_lcs_calls             = 0;
  std::uint64_t type3_edges_built           = 0;
  std::uint64_t type3_edges_selected        = 0;
  std::uint64_t type3_edges_used_rejected   = 0;
  std::uint64_t type3_edges_overlap_rejected = 0;
  std::uint64_t local_replacement_rejected    = 0;
};

group_kind classify_counts(std::size_t del_count, std::size_t ins_count) {
  if (del_count == 0 && ins_count == 0) {
    return group_kind::ambiguous;
  }
  if (del_count > 0 && ins_count == 0) {
    return group_kind::delete_only;
  }
  if (del_count == 0 && ins_count > 0) {
    return group_kind::insert_only;
  }
  if (del_count == 1 && ins_count == 1) {
    return group_kind::move_1_to_1;
  }
  if (del_count == ins_count && del_count > 1) {
    return group_kind::moves_many;
  }
  return group_kind::copy_or_repeat;
}

void add_group(content_groups                  &out,
               std::uint64_t                    content_hash,
               const std::vector<candidate_id> &del_ids,
               const std::vector<candidate_id> &ins_ids,
               match_kind                       match,
               std::uint32_t confidence_milli = 0,
               std::uint64_t selection_utility = 0,
               std::uint32_t matched_units = 0,
               std::string selection_reason = {}) {
  const std::uint32_t group_id  = static_cast<std::uint32_t>(out.group_count());
  const std::uint32_t del_begin = out.append_delete_ids(del_ids);
  const std::uint32_t del_size  = static_cast<std::uint32_t>(del_ids.size());
  const std::uint32_t del_end   = del_begin + del_size;
  const std::uint32_t ins_begin = out.append_insert_ids(ins_ids);
  const std::uint32_t ins_size  = static_cast<std::uint32_t>(ins_ids.size());
  const std::uint32_t ins_end   = ins_begin + ins_size;
  const group_kind    kind = classify_counts(del_ids.size(), ins_ids.size());

  out.append_group(content_group{
      content_hash,
      group_id,
      del_begin,
      del_end,
      ins_begin,
      ins_end,
      kind,
      match,
      confidence_milli,
      selection_utility,
      matched_units,
      std::move(selection_reason),
  });
}

struct sv_hash {
  std::size_t operator()(std::string_view s) const noexcept {
    return std::hash<std::string_view>{}(s);
  }
};

std::string exact_group_key(const move_candidate &candidate) {
  std::string key = candidate.canonical_text;
  key.push_back('\0');
  // Keep structural children from coalescing with equivalent diff wrappers.
  key.push_back(candidate.role == move_candidate::Role::structural_child ? 's'
                                                                         : 'd');
  return key;
}

void add_hash_bucket_groups(content_groups           &out,
                            const candidate_registry &registry) {
  for (const std::pair<const std::uint64_t, bucket_ids> &kv :
       registry.hash_buckets()) {
    const match_kind match =
        (!kv.second.del_ids.empty() && !kv.second.ins_ids.empty())
            ? match_kind::type1
            : match_kind::unmatched;
    add_group(out, kv.first, kv.second.del_ids, kv.second.ins_ids, match);
  }
}

void add_selected_group(content_groups           &out,
                        const candidate_registry &registry,
                        const pending_group      &group,
                        group_selection          &selection,
                        std::uint32_t confidence_milli = 0,
                        std::uint64_t selection_utility = 0,
                        std::uint32_t matched_units = 0,
                        std::string selection_reason = "greedy_utility") {
  add_group(out, group.content_hash, group.del_ids, group.ins_ids, group.match,
            confidence_milli, selection_utility, matched_units,
            std::move(selection_reason));
  selection.mark_selected(group, registry);
}

std::vector<pending_group>
build_exact_groups(const candidate_registry &registry) {
  static const std::vector<candidate_id> kEmpty;

  const std::unordered_map<std::uint64_t, bucket_ids> &hash_buckets =
      registry.hash_buckets();
  std::vector<pending_group> exact_groups;
  exact_groups.reserve(hash_buckets.size());

  // O(active candidate ids + exact groups). Candidate text is already
  // canonicalized; this phase only partitions ids by stored text keys.
  for (const auto &kv : hash_buckets) {
    const std::uint64_t content_hash = kv.first;
    const bucket_ids   &bucket       = kv.second;

    std::unordered_map<std::string, std::vector<candidate_id>> del_by_text;
    std::unordered_map<std::string, std::vector<candidate_id>> ins_by_text;

    del_by_text.reserve(bucket.del_ids.size());
    ins_by_text.reserve(bucket.ins_ids.size());

    for (candidate_id id : bucket.del_ids) {
      const candidate_registry::candidate_record &record = registry.record(id);
      if (!record.active) {
        continue;
      }
      const move_candidate &candidate = record.candidate;
      del_by_text[exact_group_key(candidate)].push_back(id);
    }

    for (candidate_id id : bucket.ins_ids) {
      const candidate_registry::candidate_record &record = registry.record(id);
      if (!record.active) {
        continue;
      }
      const move_candidate &candidate = record.candidate;
      ins_by_text[exact_group_key(candidate)].push_back(id);
    }

    std::unordered_map<std::string, bool> seen;
    seen.reserve(del_by_text.size() + ins_by_text.size());

    for (auto &entry : del_by_text) {
      const std::string         &text = entry.first;
      std::vector<candidate_id> &dels = entry.second;

      (void)seen.emplace(text, true);

      auto it = ins_by_text.find(text);
      if (it != ins_by_text.end()) {
        exact_groups.push_back(
            pending_group{content_hash, match_kind::type1, dels, it->second});
      } else {
        exact_groups.push_back(
            pending_group{content_hash, match_kind::unmatched, dels, kEmpty});
      }
    }

    for (auto &entry : ins_by_text) {
      const std::string         &text = entry.first;
      std::vector<candidate_id> &inss = entry.second;

      if (seen.find(text) != seen.end()) {
        continue;
      }

      exact_groups.push_back(
          pending_group{content_hash, match_kind::unmatched, kEmpty, inss});
    }
  }

  return exact_groups;
}

const std::vector<std::string> &ancestor_summary(
    const candidate_registry &registry, const move_candidate &candidate) {
  static const std::vector<std::string> kEmpty;
  if (!candidate.location.ancestor_summary_reliable ||
      candidate.location.ancestor_summary_id >=
          registry.ancestor_summaries().size()) {
    return kEmpty;
  }
  return registry.ancestor_summaries()[candidate.location.ancestor_summary_id];
}

endpoint_context_diagnostic endpoint_diagnostic(
    const candidate_registry &registry, const move_candidate &candidate) {
  const endpoint_location_context &context = candidate.location;
  return endpoint_context_diagnostic{
      context.revision_file,
      context.semantic_container_id,
      context.semantic_container_label,
      context.previous_common_anchor_id,
      context.next_common_anchor_id,
      ancestor_summary(registry, candidate),
      context.ancestor_summary_interpretable,
  };
}

std::string_view relative_order_observation(
    anchor_interval_observation observation) {
  switch (observation) {
  case anchor_interval_observation::same:
    return "unchanged";
  case anchor_interval_observation::crossed:
    return "crossed_stable_sibling";
  case anchor_interval_observation::different:
  case anchor_interval_observation::unknown:
    return "unknown";
  }
  return "unknown";
}

struct correspondence_decision {
  candidate_id delete_candidate_id = 0;
  candidate_id insert_candidate_id = 0;
  match_kind match = match_kind::unmatched;
  movement_classification classification;
  candidate_id parent_delete_candidate_id = 0;
  candidate_id parent_insert_candidate_id = 0;
};

std::vector<correspondence_decision>
classify_unique_correspondences(
    const candidate_registry &registry,
    const std::vector<pending_group> &groups) {
  std::vector<correspondence_decision> decisions;
  for (const pending_group &group : groups) {
    if (group.del_ids.size() != 1 || group.ins_ids.size() != 1) {
      continue;
    }
    const candidate_id del_id = group.del_ids.front();
    const candidate_id ins_id = group.ins_ids.front();
    const move_candidate &deleted = registry.candidate(del_id);
    const move_candidate &inserted = registry.candidate(ins_id);
    decisions.push_back(correspondence_decision{
        del_id, ins_id, group.match,
        classify_movement(
            deleted.location, ancestor_summary(registry, deleted),
            inserted.location, ancestor_summary(registry, inserted)),
    });
  }
  return decisions;
}

void materialize_correspondence_diagnostics(
    const candidate_registry &registry,
    const std::vector<correspondence_decision> &decisions,
    selection_diagnostics &diagnostics) {
  diagnostics.correspondences.reserve(decisions.size());
  for (const correspondence_decision &decision : decisions) {
    const movement_classification &classification = decision.classification;
    std::string anchor_interval =
        std::string(to_string(classification.observations.anchor_interval));
    std::string relative_order = std::string(relative_order_observation(
        classification.observations.anchor_interval));
    if (classification.carried_by_parent) {
      anchor_interval = "same_within_parent";
      relative_order = "unchanged";
    }
    diagnostics.correspondences.push_back(correspondence_diagnostic{
        decision.delete_candidate_id,
        decision.insert_candidate_id,
        decision.match == match_kind::type1 ? "type1" : "type2",
        "one_to_one",
        "not_move",
        std::string(to_string(classification.change_kind)),
        std::string(to_string(classification.reason)),
        std::string(to_string(classification.observations.file)),
        std::string(
            to_string(classification.observations.semantic_container)),
        std::move(anchor_interval),
        std::move(relative_order),
        std::string(to_string(classification.observations.ancestor)),
        classification.carried_by_parent,
        endpoint_diagnostic(
            registry, registry.candidate(decision.delete_candidate_id)),
        endpoint_diagnostic(
            registry, registry.candidate(decision.insert_candidate_id)),
        decision.parent_delete_candidate_id,
        decision.parent_insert_candidate_id,
    });
  }
}

void update_correspondence_selection_results(
    const content_groups &groups, selection_diagnostics &diagnostics) {
  for (correspondence_diagnostic &correspondence :
       diagnostics.correspondences) {
    const match_kind expected_match =
        correspondence.correspondence_kind == "type1"
            ? match_kind::type1 : match_kind::type2;
    const bool selected = std::any_of(
        groups.groups().begin(), groups.groups().end(),
        [&](const content_group &group) {
          if (group.match != expected_match || group.del_count() != 1 ||
              group.ins_count() != 1) {
            return false;
          }
          return groups.delete_ids(group)[0] ==
                     correspondence.delete_candidate_id &&
                 groups.insert_ids(group)[0] ==
                     correspondence.insert_candidate_id;
        });
    correspondence.current_result = selected ? "move" : "not_move";
  }
}

using normalized_group_map = std::unordered_map<std::string, pending_group>;

std::string type2_group_key(const move_candidate &candidate) {
  std::string key = candidate.full_name;
  key.push_back('\0');
  key += candidate.type2_canonical_text;
  return key;
}

std::vector<pending_group>
build_type2_groups(const candidate_registry         &registry,
                   const std::vector<pending_group> &exact_groups,
                   const std::vector<std::size_t>   &order) {
  normalized_group_map type2_groups;
  type2_groups.reserve(exact_groups.size());

  // O(unmatched exact-group ids). Candidate-local normalization is cached;
  // grouping remains linear rather than comparing every delete with every
  // insertion.
  for (std::size_t group_index : order) {
    const pending_group &group = exact_groups[group_index];
    if (has_both_sides(group)) {
      continue;
    }

    for (candidate_id id : group.del_ids) {
      const move_candidate &candidate = registry.candidate(id);
      if (!candidate.type2_eligible) {
        continue;
      }
      pending_group &type2_group = type2_groups[type2_group_key(candidate)];
      type2_group.content_hash = candidate.type2_hash;
      type2_group.match        = match_kind::type2;
      type2_group.del_ids.push_back(id);
    }

    for (candidate_id id : group.ins_ids) {
      const move_candidate &candidate = registry.candidate(id);
      if (!candidate.type2_eligible) {
        continue;
      }
      pending_group &type2_group = type2_groups[type2_group_key(candidate)];
      type2_group.content_hash = candidate.type2_hash;
      type2_group.match        = match_kind::type2;
      type2_group.ins_ids.push_back(id);
    }
  }

  std::vector<pending_group> out;
  out.reserve(type2_groups.size());
  for (auto &entry : type2_groups) {
    out.push_back(std::move(entry.second));
  }
  return out;
}

struct type3_edge {
  candidate_id del_id = 0;
  candidate_id ins_id = 0;
  std::size_t common_units = 0;
  std::size_t maximum_units = 0;
};

struct match_proposal {
  pending_group group;
  std::uint64_t utility = 0;
  std::size_t   matched_units = 0;
  std::size_t   explanatory_units = 0;
  std::size_t   covered_span = 0;
  int           evidence_strength = 0;
  int           source_construct = 0;
  std::uint32_t confidence_milli = 0;
  bool          disabled = false;
  std::string   selection_reason = "greedy_utility";
};

std::size_t candidate_units(const move_candidate &candidate) {
  if (!candidate.type3_normalized_tokens.empty()) {
    return candidate.type3_normalized_tokens.size();
  }
  if (!candidate.type2_normalized_lines.empty()) {
    return candidate.type2_normalized_lines.size();
  }
  return static_cast<std::size_t>(std::count_if(
      candidate.raw_text.begin(), candidate.raw_text.end(),
      [](unsigned char c) { return !std::isspace(c); }));
}

std::size_t candidate_span(const move_candidate &candidate) {
  return candidate.end_idx >= candidate.start_idx
             ? candidate.end_idx - candidate.start_idx + 1
             : 0;
}

bool candidates_overlap(const move_candidate &lhs,
                        const move_candidate &rhs) {
  return lhs.kind == rhs.kind && lhs.filename == rhs.filename &&
         lhs.start_idx <= rhs.end_idx && rhs.start_idx <= lhs.end_idx;
}

std::vector<candidate_id> non_overlapping_exact_endpoints(
    const candidate_registry &registry,
    const std::vector<candidate_id> &ids) {
  std::vector<candidate_id> ordered = ids;
  std::sort(ordered.begin(), ordered.end(),
            [&registry](candidate_id lhs, candidate_id rhs) {
              const std::size_t lhs_span =
                  candidate_span(registry.candidate(lhs));
              const std::size_t rhs_span =
                  candidate_span(registry.candidate(rhs));
              return lhs_span != rhs_span ? lhs_span < rhs_span : lhs < rhs;
            });

  std::vector<candidate_id> selected;
  for (candidate_id id : ordered) {
    const move_candidate &candidate = registry.candidate(id);
    const bool overlaps = std::any_of(
        selected.begin(), selected.end(), [&](candidate_id selected_id) {
          return candidates_overlap(candidate,
                                    registry.candidate(selected_id));
        });
    if (!overlaps) {
      selected.push_back(id);
    }
  }
  std::sort(selected.begin(), selected.end());
  return selected;
}

std::size_t proposal_span(const pending_group      &group,
                          const candidate_registry &registry) {
  std::size_t total = 0;
  const auto add = [&](candidate_id id) {
    total += candidate_span(registry.candidate(id));
  };
  for (candidate_id id : group.del_ids)
    add(id);
  for (candidate_id id : group.ins_ids)
    add(id);
  return total;
}

match_proposal make_pair_proposal(const candidate_registry &registry,
                                  candidate_id del_id,
                                  candidate_id ins_id,
                                  match_kind match,
                                  std::size_t matched_units,
                                  std::uint64_t confidence_milli) {
  pending_group group;
  group.content_hash = registry.candidate(del_id).hash;
  group.match = match;
  group.del_ids.push_back(del_id);
  group.ins_ids.push_back(ins_id);
  const std::size_t covered_span = proposal_span(group, registry);
  const int source_construct =
      registry.candidate(del_id).role ==
              move_candidate::Role::structural_child &&
          registry.candidate(ins_id).role ==
              move_candidate::Role::structural_child
      ? 1
      : 0;
  return match_proposal{std::move(group),
                        matched_units * confidence_milli,
                        matched_units,
                        matched_units,
                        covered_span,
                        match == match_kind::type1
                            ? 3
                            : (match == match_kind::type2 ? 2 : 1),
                        source_construct,
                        static_cast<std::uint32_t>(confidence_milli),
                        false,
                        "greedy_utility"};
}

match_proposal make_exact_group_proposal(
    const candidate_registry &registry, const pending_group &group) {
  pending_group resolved = group;
  resolved.del_ids = non_overlapping_exact_endpoints(registry, group.del_ids);
  resolved.ins_ids = non_overlapping_exact_endpoints(registry, group.ins_ids);
  const auto side_units = [&registry](const std::vector<candidate_id> &ids) {
    std::size_t total = 0;
    for (candidate_id id : ids) {
      total += candidate_units(registry.candidate(id));
    }
    return total;
  };
  const std::size_t matched_units =
      std::min(side_units(resolved.del_ids), side_units(resolved.ins_ids));
  const std::size_t ambiguity =
      std::max(resolved.del_ids.size(), resolved.ins_ids.size());
  const std::uint32_t confidence_milli = static_cast<std::uint32_t>(
      ambiguity == 0 ? 0 : 1000 / ambiguity);
  const bool all_source_constructs =
      std::all_of(resolved.del_ids.begin(), resolved.del_ids.end(),
                  [&registry](candidate_id id) {
                    return registry.candidate(id).role ==
                           move_candidate::Role::structural_child;
                  }) &&
      std::all_of(resolved.ins_ids.begin(), resolved.ins_ids.end(),
                  [&registry](candidate_id id) {
                    return registry.candidate(id).role ==
                           move_candidate::Role::structural_child;
                  });
  return match_proposal{resolved,
                        matched_units * confidence_milli,
                        matched_units,
                        matched_units,
                        proposal_span(resolved, registry),
                        3,
                        all_source_constructs ? 1 : 0,
                        confidence_milli,
                        false,
                        "greedy_utility"};
}

candidate_id proposal_min_id(const match_proposal &proposal) {
  return std::min(proposal.group.del_ids.front(),
                  proposal.group.ins_ids.front());
}

bool proposal_better(const match_proposal &lhs, const match_proposal &rhs) {
  const auto key = [](const match_proposal &proposal) {
    return proposal_rank_key{
        proposal.utility,
        proposal.explanatory_units,
        proposal.matched_units,
        proposal.evidence_strength,
        proposal.source_construct,
        proposal.covered_span,
        proposal_min_id(proposal),
        proposal.group.del_ids.front(),
        proposal.group.ins_ids.front(),
    };
  };
  return proposal_rank_better(key(lhs), key(rhs));
}

std::vector<match_proposal> build_match_proposals(
    const candidate_registry &registry,
    const std::vector<pending_group> &exact_groups,
    const std::vector<pending_group> &type2_groups,
    const std::vector<type3_edge> &type3_edges) {
  std::vector<match_proposal> proposals;

  for (const pending_group &group : exact_groups) {
    if (!has_both_sides(group))
      continue;
    if (group.del_ids.size() == 1 && group.ins_ids.size() == 1) {
      const candidate_id del_id = group.del_ids.front();
      const candidate_id ins_id = group.ins_ids.front();
      proposals.push_back(make_pair_proposal(
          registry, del_id, ins_id, match_kind::type1,
          std::min(candidate_units(registry.candidate(del_id)),
                   candidate_units(registry.candidate(ins_id))),
          1000));
    } else {
      proposals.push_back(make_exact_group_proposal(registry, group));
    }
  }

  for (const pending_group &group : type2_groups) {
    if (group.del_ids.size() != 1 || group.ins_ids.size() != 1)
      continue;
    const candidate_id del_id = group.del_ids.front();
    const candidate_id ins_id = group.ins_ids.front();
    proposals.push_back(make_pair_proposal(
        registry, del_id, ins_id, match_kind::type2,
        std::min(candidate_units(registry.candidate(del_id)),
                 candidate_units(registry.candidate(ins_id))),
        950));
  }

  for (const type3_edge &edge : type3_edges) {
    const std::size_t coverage_units =
        std::min(candidate_units(registry.candidate(edge.del_id)),
                 candidate_units(registry.candidate(edge.ins_id)));
    const std::uint64_t confidence_milli =
        edge.maximum_units == 0
            ? 0
            : static_cast<std::uint64_t>(edge.common_units) * 1000 /
                  edge.maximum_units;
    match_proposal proposal = make_pair_proposal(
        registry, edge.del_id, edge.ins_id, match_kind::type3,
        coverage_units, confidence_milli);
    const std::uint64_t unmatched_penalty =
        static_cast<std::uint64_t>(coverage_units) *
        (1000 - confidence_milli) / 2;
    proposal.utility -= std::min(proposal.utility, unmatched_penalty);
    proposal.matched_units = static_cast<std::size_t>(
        static_cast<std::uint64_t>(coverage_units) * confidence_milli / 1000);
    proposals.push_back(std::move(proposal));
  }

  std::sort(proposals.begin(), proposals.end(), proposal_better);
  return proposals;
}

const correspondence_decision *find_correspondence_decision(
    const std::vector<correspondence_decision> &decisions,
    candidate_id delete_id, candidate_id insert_id) {
  const auto key = std::pair{delete_id, insert_id};
  const auto found = std::lower_bound(
      decisions.begin(), decisions.end(), key,
      [](const correspondence_decision &decision,
         const std::pair<candidate_id, candidate_id> &wanted) {
        return std::pair{decision.delete_candidate_id,
                         decision.insert_candidate_id} < wanted;
      });
  if (found == decisions.end() || found->delete_candidate_id != delete_id ||
      found->insert_candidate_id != insert_id) {
    return nullptr;
  }
  return &*found;
}

void apply_type1_output_policy(
    std::vector<match_proposal> &proposals,
    const std::vector<correspondence_decision> &decisions,
    grouping_profile_stats *stats) {
  for (match_proposal &proposal : proposals) {
    if (proposal.group.match != match_kind::type1 ||
        proposal.group.del_ids.size() != 1 ||
        proposal.group.ins_ids.size() != 1) {
      continue;
    }
    const correspondence_decision *decision = find_correspondence_decision(
        decisions, proposal.group.del_ids.front(),
        proposal.group.ins_ids.front());
    assert(decision != nullptr);
    if (decision != nullptr &&
        !move_eligible(decision->classification)) {
      proposal.disabled = true;
      if (stats != nullptr) {
        ++stats->type1_policy_rejected;
      }
    }
  }
}

void reject_local_replacement_proposals(
    std::vector<match_proposal> &proposals,
    const candidate_registry &registry,
    grouping_profile_stats *stats) {
  proposals.erase(
      std::remove_if(
          proposals.begin(), proposals.end(),
          [&](const match_proposal &proposal) {
            if (proposal.group.match != match_kind::type2 ||
                proposal.group.del_ids.size() != 1 ||
                proposal.group.ins_ids.size() != 1) {
              return false;
            }
            const move_candidate &deleted =
                registry.candidate(proposal.group.del_ids.front());
            const move_candidate &inserted =
                registry.candidate(proposal.group.ins_ids.front());
            const bool local_replacement = local_replacement_pair(
                local_replacement_context{
                    deleted.filename,
                    deleted.structural_parent_depth,
                    deleted.diff_region_start_idx,
                    deleted.diff_region_end_idx,
                },
                local_replacement_context{
                    inserted.filename,
                    inserted.structural_parent_depth,
                    inserted.diff_region_start_idx,
                    inserted.diff_region_end_idx,
                });
            if (local_replacement && stats != nullptr) {
              ++stats->local_replacement_rejected;
            }
            return local_replacement;
          }),
      proposals.end());
}

bool candidate_strictly_contains(const move_candidate &outer,
                                 const move_candidate &inner) {
  return outer.kind == inner.kind && outer.filename == inner.filename &&
         outer.start_idx <= inner.start_idx && inner.end_idx <= outer.end_idx &&
         (outer.start_idx < inner.start_idx || inner.end_idx < outer.end_idx);
}

void classify_parent_carried_correspondences(
    const candidate_registry &registry,
    std::vector<correspondence_decision> &decisions) {
  const std::vector<bool> independently_relocated = [&decisions] {
    std::vector<bool> result;
    result.reserve(decisions.size());
    for (const correspondence_decision &item : decisions) {
      result.push_back(item.match == match_kind::type1 &&
                       item.classification.change_kind == movement_kind::relocated);
    }
    return result;
  }();

  for (std::size_t child_index = 0; child_index < decisions.size();
       ++child_index) {
    correspondence_decision &child = decisions[child_index];
    if (child.match != match_kind::type1) {
      continue;
    }
    const move_candidate &child_del =
        registry.candidate(child.delete_candidate_id);
    const move_candidate &child_ins =
        registry.candidate(child.insert_candidate_id);
    if (child_del.role != move_candidate::Role::structural_child ||
        child_ins.role != move_candidate::Role::structural_child) {
      continue;
    }

    std::size_t best_parent = decisions.size();
    std::size_t best_span = 0;
    for (std::size_t parent_index = 0; parent_index < decisions.size();
         ++parent_index) {
      if (parent_index == child_index ||
          !independently_relocated[parent_index]) {
        continue;
      }
      const correspondence_decision &parent = decisions[parent_index];
      const move_candidate &parent_del =
          registry.candidate(parent.delete_candidate_id);
      const move_candidate &parent_ins =
          registry.candidate(parent.insert_candidate_id);
      if (parent_del.role != move_candidate::Role::structural_child ||
          parent_ins.role != move_candidate::Role::structural_child ||
          !candidate_strictly_contains(parent_del, child_del) ||
          !candidate_strictly_contains(parent_ins, child_ins)) {
        continue;
      }
      const std::size_t span = candidate_span(parent_del) +
                               candidate_span(parent_ins);
      if (best_parent == decisions.size() ||
          span < best_span ||
          (span == best_span &&
           std::pair{parent.delete_candidate_id,
                     parent.insert_candidate_id} <
               std::pair{decisions[best_parent].delete_candidate_id,
                         decisions[best_parent].insert_candidate_id})) {
        best_parent = parent_index;
        best_span = span;
      }
    }

    if (best_parent == decisions.size()) {
      continue;
    }
    const correspondence_decision &parent = decisions[best_parent];
    child.classification.change_kind = movement_kind::stationary;
    child.classification.reason =
        movement_classification_reason::stable_relative_to_relocated_parent;
    child.classification.carried_by_parent = true;
    child.parent_delete_candidate_id = parent.delete_candidate_id;
    child.parent_insert_candidate_id = parent.insert_candidate_id;
  }
}

void order_correspondence_decisions(
    std::vector<correspondence_decision> &decisions) {
  std::sort(
      decisions.begin(), decisions.end(),
      [](const correspondence_decision &lhs,
         const correspondence_decision &rhs) {
        return std::pair{lhs.delete_candidate_id, lhs.insert_candidate_id} <
               std::pair{rhs.delete_candidate_id, rhs.insert_candidate_id};
      });
}

bool proposal_is_descendant(const match_proposal &child,
                            const match_proposal &parent,
                            const candidate_registry &registry) {
  if (child.group.del_ids.size() != 1 || child.group.ins_ids.size() != 1 ||
      parent.group.del_ids.size() != 1 || parent.group.ins_ids.size() != 1) {
    return false;
  }
  return candidate_strictly_contains(
             registry.candidate(parent.group.del_ids.front()),
             registry.candidate(child.group.del_ids.front())) &&
         candidate_strictly_contains(
             registry.candidate(parent.group.ins_ids.front()),
             registry.candidate(child.group.ins_ids.front()));
}

bool descendant_bundle_is_preferred(
    const match_proposal &parent,
    const std::vector<std::size_t> &children,
    const std::vector<match_proposal> &proposals,
    const candidate_registry &registry) {
  if (children.size() < 2 || parent.group.del_ids.size() != 1 ||
      parent.group.ins_ids.size() != 1) {
    return false;
  }

  const std::size_t parent_del_units =
      candidate_units(registry.candidate(parent.group.del_ids.front()));
  const std::size_t parent_ins_units =
      candidate_units(registry.candidate(parent.group.ins_ids.front()));
  std::uint64_t child_del_units     = 0;
  std::uint64_t child_ins_units     = 0;
  std::uint64_t matched_units       = 0;
  std::uint64_t weighted_confidence = 0;
  std::uint64_t utility_sum         = 0;

  for (std::size_t child_index : children) {
    const match_proposal &child = proposals[child_index];
    child_del_units += candidate_units(
        registry.candidate(child.group.del_ids.front()));
    child_ins_units += candidate_units(
        registry.candidate(child.group.ins_ids.front()));
    matched_units += child.matched_units;
    weighted_confidence += child.confidence_milli * child.matched_units;
    utility_sum += child.utility;
  }

  return descendant_bundle_preferred(descendant_bundle_metrics{
      parent.utility,
      parent.confidence_milli,
      parent_del_units,
      parent_ins_units,
      utility_sum,
      matched_units,
      weighted_confidence,
      child_del_units,
      child_ins_units,
      children.size(),
  });
}

void prefer_stronger_descendant_bundles(
    std::vector<match_proposal> &proposals,
    const candidate_registry &registry) {
  std::vector<std::size_t> parents(proposals.size());
  std::iota(parents.begin(), parents.end(), 0);
  std::sort(parents.begin(), parents.end(), [&proposals](std::size_t lhs,
                                                         std::size_t rhs) {
    if (proposals[lhs].covered_span != proposals[rhs].covered_span) {
      return proposals[lhs].covered_span > proposals[rhs].covered_span;
    }
    return lhs < rhs;
  });

  for (std::size_t parent_index : parents) {
    match_proposal &parent = proposals[parent_index];
    if (parent.disabled)
      continue;

    group_selection descendants(registry.total_record_count());
    std::vector<std::size_t> chosen;
    for (std::size_t child_index = 0; child_index < proposals.size();
         ++child_index) {
      match_proposal &child = proposals[child_index];
      if (child_index == parent_index || child.disabled ||
          !proposal_is_descendant(child, parent, registry) ||
          descendants.group_conflicts(child.group, registry)) {
        continue;
      }
      descendants.mark_selected(child.group, registry);
      chosen.push_back(child_index);
    }

    if (!descendant_bundle_is_preferred(parent, chosen, proposals, registry)) {
      continue;
    }

    parent.disabled = true;
    for (std::size_t child_index : chosen) {
      proposals[child_index].selection_reason = "descendant_bundle";
    }
  }
}

bool type3_edge_better(const type3_edge &lhs, const type3_edge &rhs) {
  const std::size_t lhs_scaled = lhs.common_units * rhs.maximum_units;
  const std::size_t rhs_scaled = rhs.common_units * lhs.maximum_units;
  if (lhs_scaled != rhs_scaled) {
    return lhs_scaled > rhs_scaled;
  }
  if (lhs.maximum_units != rhs.maximum_units) {
    return lhs.maximum_units > rhs.maximum_units;
  }
  if (lhs.del_id != rhs.del_id) {
    return lhs.del_id < rhs.del_id;
  }
  return lhs.ins_id < rhs.ins_id;
}

std::vector<candidate_id>
collect_type3_ids(const candidate_registry         &registry,
                  const std::vector<pending_group> &exact_groups,
                  const std::vector<std::size_t>   &order,
                  move_candidate::Kind              kind) {
  std::vector<candidate_id> ids;
  for (std::size_t group_index : order) {
    const pending_group &group = exact_groups[group_index];
    if (has_both_sides(group)) {
      continue;
    }
    const std::vector<candidate_id> &side =
        kind == move_candidate::Kind::del ? group.del_ids : group.ins_ids;
    for (candidate_id id : side) {
      const move_candidate &candidate = registry.candidate(id);
      if (!candidate.type2_eligible ||
          candidate.role != move_candidate::Role::structural_child ||
          (candidate.type2_normalized_lines.empty() ||
           candidate.type3_normalized_tokens.empty())) {
        continue;
      }
      ids.push_back(id);
    }
  }
  return ids;
}

std::vector<type3_edge>
build_type3_edges(const candidate_registry         &registry,
                  const std::vector<pending_group> &exact_groups,
                  const std::vector<std::size_t>   &order,
                  grouping_profile_stats           *stats,
                  selection_diagnostics             *diagnostics) {
  const std::vector<candidate_id> del_ids = collect_type3_ids(
      registry, exact_groups, order, move_candidate::Kind::del);
  const std::vector<candidate_id> ins_ids = collect_type3_ids(
      registry, exact_groups, order, move_candidate::Kind::insert);
  if (stats != nullptr) {
    stats->type3_delete_candidates = del_ids.size();
    stats->type3_insert_candidates = ins_ids.size();
  }

  struct type3_bucket {
    std::vector<candidate_id> by_lines;
    std::vector<candidate_id> by_tokens;
  };
  std::unordered_map<std::string_view, type3_bucket, sv_hash>
      insert_buckets;
  for (candidate_id id : ins_ids) {
    type3_bucket &bucket = insert_buckets[registry.candidate(id).full_name];
    bucket.by_lines.push_back(id);
    bucket.by_tokens.push_back(id);
  }
  const auto line_count = [&registry](candidate_id id) {
    return registry.candidate(id).type2_normalized_lines.size();
  };
  const auto token_count = [&registry](candidate_id id) {
    return registry.candidate(id).type3_normalized_tokens.size();
  };
  const auto sort_by_size = [](std::vector<candidate_id> &ids,
                               const auto                &size_of) {
    std::sort(ids.begin(), ids.end(),
              [&size_of](candidate_id lhs, candidate_id rhs) {
                const std::size_t lhs_size = size_of(lhs);
                const std::size_t rhs_size = size_of(rhs);
                return lhs_size != rhs_size ? lhs_size < rhs_size : lhs < rhs;
              });
  };
  for (auto &entry : insert_buckets) {
    sort_by_size(entry.second.by_lines, line_count);
    sort_by_size(entry.second.by_tokens, token_count);
  }

  const auto append_size_window = [](std::vector<candidate_id>       &out,
                                     const std::vector<candidate_id> &ids,
                                     std::size_t                      query_size,
                                     const auto                      &size_of) {
    const std::size_t minimum_size =
        (query_size * kType3ThresholdNumerator +
         kType3ThresholdDenominator - 1) /
        kType3ThresholdDenominator;
    const std::size_t maximum_size =
        query_size * kType3ThresholdDenominator / kType3ThresholdNumerator;
    const auto first = std::lower_bound(
        ids.begin(), ids.end(), minimum_size,
        [&size_of](candidate_id id, std::size_t size) {
          return size_of(id) < size;
        });
    const auto last = std::upper_bound(
        first, ids.end(), maximum_size,
        [&size_of](std::size_t size, candidate_id id) {
          return size < size_of(id);
        });
    out.insert(out.end(), first, last);
  };

  std::vector<type3_edge> edges;
  for (candidate_id del_id : del_ids) {
    const move_candidate &del = registry.candidate(del_id);
    const auto bucket = insert_buckets.find(del.full_name);
    if (bucket == insert_buckets.end()) {
      continue;
    }

    std::vector<candidate_id> candidates;
    append_size_window(candidates, bucket->second.by_lines,
                       del.type2_normalized_lines.size(), line_count);
    append_size_window(candidates, bucket->second.by_tokens,
                       del.type3_normalized_tokens.size(), token_count);
    std::sort(candidates.begin(), candidates.end());
    candidates.erase(std::unique(candidates.begin(), candidates.end()),
                     candidates.end());
    if (stats != nullptr) {
      stats->type3_shortlist_entries += candidates.size();
    }

    for (candidate_id ins_id : candidates) {
      const move_candidate &ins = registry.candidate(ins_id);
      // An exact Type-2 identity that was rejected only because its group was
      // ambiguous must not be relabeled as a weaker one-to-one Type-3 match.
      if (del.type2_canonical_text == ins.type2_canonical_text) {
        if (diagnostics != nullptr) {
          diagnostics->type3_pairs.push_back(type3_pair_diagnostic{
              del_id, ins_id, "ambiguous_type2", 0,
              std::max(del.type2_normalized_lines.size(),
                       ins.type2_normalized_lines.size()),
              0,
              std::max(del.type3_normalized_tokens.size(),
                       ins.type3_normalized_tokens.size())});
        }
        continue;
      }

      if (stats != nullptr) {
        ++stats->type3_pairs_considered;
        stats->type3_lcs_calls += 2;
      }

      const std::size_t common_lines = type3_lcs_length(
          del.type2_normalized_lines, ins.type2_normalized_lines);
      const std::size_t common_tokens = type3_lcs_length(
          del.type3_normalized_tokens, ins.type3_normalized_tokens);
      const std::size_t maximum_lines =
          std::max(del.type2_normalized_lines.size(),
                   ins.type2_normalized_lines.size());
      const std::size_t maximum_tokens =
          std::max(del.type3_normalized_tokens.size(),
                   ins.type3_normalized_tokens.size());
      if (diagnostics != nullptr) {
        const std::size_t observed_common_lines =
            common_lines != 0
                ? common_lines
                : bounded_lcs_length(del.type2_normalized_lines,
                                     ins.type2_normalized_lines, 1);
        const std::size_t observed_common_tokens =
            common_tokens != 0
                ? common_tokens
                : bounded_lcs_length(del.type3_normalized_tokens,
                                     ins.type3_normalized_tokens, 1);
        diagnostics->type3_pairs.push_back(type3_pair_diagnostic{
            del_id,
            ins_id,
            common_lines == 0 && common_tokens == 0 ? "below_threshold"
                                                    : "verified_edge",
            observed_common_lines,
            maximum_lines,
            observed_common_tokens,
            maximum_tokens});
      }
      if (common_lines == 0 && common_tokens == 0) {
        continue;
      }

      const bool tokens_are_stronger =
          common_tokens != 0 &&
          (common_lines == 0 ||
           common_tokens * maximum_lines > common_lines * maximum_tokens);
      edges.push_back(type3_edge{
          del_id, ins_id,
          tokens_are_stronger ? common_tokens : common_lines,
          tokens_are_stronger ? maximum_tokens : maximum_lines});
    }
  }

  std::sort(edges.begin(), edges.end(), type3_edge_better);
  if (stats != nullptr) {
    stats->type3_edges_built = edges.size();
  }
  return edges;
}

void add_unmatched_exact_groups(content_groups                   &out,
                                const candidate_registry         &registry,
                                const std::vector<pending_group> &exact_groups,
                                const std::vector<std::size_t>   &order,
                                const group_selection            &selection) {
  // O(unmatched exact-group ids * covered spans) in the worst case because
  // suppression checks scan selected covered spans.
  for (std::size_t group_index : order) {
    const pending_group &group = exact_groups[group_index];
    if (has_both_sides(group)) {
      continue;
    }

    std::vector<candidate_id> del_ids =
        filter_unselected_ids(group.del_ids, registry, selection);
    std::vector<candidate_id> ins_ids =
        filter_unselected_ids(group.ins_ids, registry, selection);
    if (del_ids.empty() && ins_ids.empty()) {
      continue;
    }

    add_group(out, group.content_hash, del_ids, ins_ids, match_kind::unmatched);
  }
}

} // namespace

content_groups build_content_groups(const candidate_registry &registry,
                                    content_grouping_mode mode,
                                    profile_report *profile,
                                    selection_diagnostics *diagnostics) {
  scoped_profile_timer total_timer(profile, "content_groups.total");
  grouping_profile_stats profile_stats;
  grouping_profile_stats *stats = profile == nullptr ? nullptr : &profile_stats;

  content_groups out;
  out.reserve_groups(registry.hash_buckets().size());

  if (mode == content_grouping_mode::hash_bucket_only) {
    scoped_profile_timer timer(profile, "content_groups.hash_bucket_only");
    add_hash_bucket_groups(out, registry);
    return out;
  }

  std::vector<pending_group> exact_groups;
  std::vector<correspondence_decision> decisions;
  {
    scoped_profile_timer timer(profile, "content_groups.exact_build");
    exact_groups = build_exact_groups(registry);
    if (stats != nullptr) {
      stats->exact_groups_built = exact_groups.size();
    }
    decisions =
        classify_unique_correspondences(registry, exact_groups);
    classify_parent_carried_correspondences(registry, decisions);
    order_correspondence_decisions(decisions);
  }

  std::vector<std::size_t> exact_group_order;
  {
    scoped_profile_timer timer(profile, "content_groups.exact_order");
    exact_group_order = group_selection_order(exact_groups, registry);
  }

  group_selection selection(registry.active_candidate_count());

  std::vector<pending_group> type2_groups;
  {
    scoped_profile_timer timer(profile, "content_groups.type2_build");
    type2_groups =
        build_type2_groups(registry, exact_groups, exact_group_order);
    if (stats != nullptr) {
      stats->type2_groups_built = type2_groups.size();
    }
  }

  std::vector<type3_edge> type3_edges;
  {
    scoped_profile_timer timer(profile, "content_groups.type3_build");
    type3_edges =
        build_type3_edges(registry, exact_groups, exact_group_order, stats,
                          diagnostics);
  }

  {
    scoped_profile_timer timer(profile, "content_groups.unified_select");
    std::vector<match_proposal> proposals = build_match_proposals(
        registry, exact_groups, type2_groups, type3_edges);
    apply_type1_output_policy(proposals, decisions, stats);
    reject_local_replacement_proposals(proposals, registry, stats);
    prefer_stronger_descendant_bundles(proposals, registry);
    for (const match_proposal &proposal : proposals) {
      if (proposal.disabled) {
        continue;
      }
      if (selection.group_conflicts(proposal.group, registry)) {
        if (stats != nullptr && proposal.group.match == match_kind::type3) {
          ++stats->type3_edges_overlap_rejected;
        }
        continue;
      }
      add_selected_group(
          out, registry, proposal.group, selection, proposal.confidence_milli,
          proposal.utility, static_cast<std::uint32_t>(proposal.matched_units),
          proposal.selection_reason);
      if (stats == nullptr)
        continue;
      switch (proposal.group.match) {
      case match_kind::type1:
        ++stats->type1_groups_selected;
        break;
      case match_kind::type2:
        ++stats->type2_groups_selected;
        break;
      case match_kind::type3:
        ++stats->type3_edges_selected;
        break;
      case match_kind::unmatched:
        break;
      }
    }
  }

  if (diagnostics != nullptr) {
    // Type-2 classification is observation-only until its adoption has been
    // evaluated. Do not extend exact-parent carrying to edited parents.
    auto type2_decisions = classify_unique_correspondences(registry, type2_groups);
    decisions.insert(decisions.end(), type2_decisions.begin(),
                     type2_decisions.end());
    order_correspondence_decisions(decisions);
    materialize_correspondence_diagnostics(registry, decisions, *diagnostics);
    update_correspondence_selection_results(out, *diagnostics);
    for (type3_pair_diagnostic &pair : diagnostics->type3_pairs) {
      if (pair.outcome != "verified_edge") {
        continue;
      }
      const bool selected = std::any_of(
          out.groups().begin(), out.groups().end(),
          [&](const content_group &group) {
            if (group.match != match_kind::type3) {
              return false;
            }
            const content_groups::id_view dels = out.delete_ids(group);
            const content_groups::id_view inss = out.insert_ids(group);
            return std::find(dels.begin(), dels.end(), pair.del_candidate_id) !=
                       dels.end() &&
                   std::find(inss.begin(), inss.end(), pair.ins_candidate_id) !=
                       inss.end();
          });
      pair.outcome = selected ? "selected" : "selection_rejected";
    }
  }

  {
    scoped_profile_timer timer(profile, "content_groups.unmatched_emit");
    add_unmatched_exact_groups(out, registry, exact_groups, exact_group_order,
                               selection);
  }

#ifndef NDEBUG
  for (const content_group &g : out.groups()) {
    assert(g.del_count() + g.ins_count() > 0);
  }
#endif

  if (profile != nullptr) {
    profile->add_counter("content_groups.exact_groups_built",
                         profile_stats.exact_groups_built);
    profile->add_counter("content_groups.type1_groups_selected",
                         profile_stats.type1_groups_selected);
    profile->add_counter("content_groups.type1_policy_rejected",
                         profile_stats.type1_policy_rejected);
    profile->add_counter("content_groups.type2_groups_built",
                         profile_stats.type2_groups_built);
    profile->add_counter("content_groups.type2_groups_selected",
                         profile_stats.type2_groups_selected);
    profile->add_counter("content_groups.type3_delete_candidates",
                         profile_stats.type3_delete_candidates);
    profile->add_counter("content_groups.type3_insert_candidates",
                         profile_stats.type3_insert_candidates);
    profile->add_counter("content_groups.type3_shortlist_entries",
                         profile_stats.type3_shortlist_entries);
    profile->add_counter("content_groups.type3_pairs_considered",
                         profile_stats.type3_pairs_considered);
    profile->add_counter("content_groups.type3_lcs_calls",
                         profile_stats.type3_lcs_calls);
    profile->add_counter("content_groups.type3_edges_built",
                         profile_stats.type3_edges_built);
    profile->add_counter("content_groups.type3_edges_selected",
                         profile_stats.type3_edges_selected);
    profile->add_counter("content_groups.type3_edges_used_rejected",
                         profile_stats.type3_edges_used_rejected);
    profile->add_counter("content_groups.type3_edges_overlap_rejected",
                         profile_stats.type3_edges_overlap_rejected);
    profile->add_counter("content_groups.local_replacement_rejected",
                         profile_stats.local_replacement_rejected);
  }

  return out;
}

} // namespace srcmove
