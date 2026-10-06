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
#include <optional>
#include <limits>
#include <map>
#include <tuple>
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

// Normalization proposes identity; only independent continuing-source pairs
// can establish concrete name replacements. Never learn from a proposed move.
std::string normalized_identity_reason(const move_candidate &deleted,
                                       const move_candidate &inserted,
                                       bool exact_normalized) {
  const auto &old_names = deleted.identifier_names;
  const auto &new_names = inserted.identifier_names;
  bool supported = false;
  bool changed = false;
  bool unsupported_change = false;
  auto observe = [&](const auto &map, const std::string &old_name,
                     const std::string &new_name) {
    auto found = map.find(old_name);
    if (found == map.end()) return 0;
    if (found->second.empty()) return 2;
    return found->second == new_name ? 1 : -1;
  };
  if (exact_normalized && deleted.member_accesses.size() == inserted.member_accesses.size()) {
    for (std::size_t i = 0; i < deleted.member_accesses.size(); ++i) {
      const auto &old_member = deleted.member_accesses[i];
      const auto &new_member = inserted.member_accesses[i];
      if (old_member.second != new_member.second) continue;
      int forward = deleted.continuing_fields ? observe(deleted.continuing_fields->forward, old_member.first, new_member.first) : 0;
      int reverse = inserted.continuing_fields ? observe(inserted.continuing_fields->reverse, new_member.first, old_member.first) : 0;
      if (forward < 0 || reverse < 0) return "continuing_name_conflict";
    }
  }
  if (exact_normalized && old_names.size() == new_names.size()) {
    for (std::size_t i = 0; i < old_names.size(); ++i) {
      if (builtin_type_name(old_names[i]) || builtin_type_name(new_names[i])) continue;
      changed |= old_names[i] != new_names[i];
      const bool plain = i < deleted.identifier_qualifiers.size() &&
          i < inserted.identifier_qualifiers.size() &&
          deleted.identifier_qualifiers[i].empty() && inserted.identifier_qualifiers[i].empty();
      int forward = plain && deleted.continuing_names
          ? observe(deleted.continuing_names->forward, old_names[i], new_names[i]) : 0;
      int reverse = plain && inserted.continuing_names
          ? observe(inserted.continuing_names->reverse, new_names[i], old_names[i]) : 0;
      if (i < deleted.identifier_qualifiers.size() &&
          i < inserted.identifier_qualifiers.size() &&
          !deleted.identifier_qualifiers[i].empty() &&
          deleted.identifier_qualifiers[i] != "$ambiguous" &&
          deleted.identifier_qualifiers[i] == inserted.identifier_qualifiers[i]) {
        const auto &prefix = deleted.identifier_qualifiers[i];
        int field_forward = deleted.continuing_fields ?
            observe(deleted.continuing_fields->forward, prefix + old_names[i], prefix + new_names[i]) : 0;
        int field_reverse = inserted.continuing_fields ?
            observe(inserted.continuing_fields->reverse, prefix + new_names[i], prefix + old_names[i]) : 0;
        if (field_forward < 0 || field_reverse < 0) return "continuing_name_conflict";
        if (forward == 0) forward = field_forward;
        if (reverse == 0) reverse = field_reverse;
      }
      if (forward < 0 || reverse < 0) return "continuing_name_conflict";
      if (old_names[i] != new_names[i] && forward != 2 && reverse != 2 &&
          (forward == 1 || reverse == 1)) supported = true;
      if (old_names[i] != new_names[i] &&
          (forward == 2 || reverse == 2 || (forward != 1 && reverse != 1)))
        unsupported_change = true;
    }
  } else {
    // Type-3 ordinal placeholders can shift after inserted identifiers. Do not
    // invent a pairwise substitution from their ordinal position; require a
    // known continuation of a missing name to occur in the target instead.
    auto check_missing_names = [&](const move_candidate &source,
                                   const move_candidate &target,
                                   bool forward) {
      for (std::size_t i = 0; i < source.identifier_names.size(); ++i) {
        const auto &name = source.identifier_names[i];
        if (builtin_type_name(name) ||
            std::find(target.identifier_names.begin(), target.identifier_names.end(), name) != target.identifier_names.end()) continue;
        changed = true;
        const auto &prefix = source.identifier_qualifiers[i];
        const auto *evidence = prefix.empty() ? source.continuing_names.get()
                                              : source.continuing_fields.get();
        if (!evidence || prefix == "$ambiguous") { unsupported_change = true; continue; }
        const auto &map = forward ? evidence->forward : evidence->reverse;
        auto found = map.find(prefix + name);
        if (found == map.end() || found->second.empty()) { unsupported_change = true; continue; }
        bool present = false;
        for (std::size_t j = 0; j < target.identifier_names.size(); ++j)
          if (target.identifier_qualifiers[j] == prefix &&
              prefix + target.identifier_names[j] == found->second) present = true;
        if (!present) return false;
        supported = true;
      }
      return true;
    };
    if (!check_missing_names(deleted, inserted, true) ||
        !check_missing_names(inserted, deleted, false)) return "continuing_name_conflict";
  }

  // A standalone renamed declaration has no internal use correspondence. A
  // size threshold cannot turn its normalized skeleton into reliable identity.
  if (changed && deleted.full_name == "decl_stmt" &&
      inserted.full_name == "decl_stmt" && (!supported || unsupported_change))
    return "uncorroborated_declaration";
  return supported ? "continuing_name_corroborated" : "";
}

bool identity_rejected(std::string_view reason) {
  return reason == "continuing_name_conflict" ||
         reason == "uncorroborated_declaration";
}

struct correspondence_decision {
  candidate_id delete_candidate_id = 0;
  candidate_id insert_candidate_id = 0;
  match_kind match = match_kind::unmatched;
  movement_classification classification;
  candidate_id parent_delete_candidate_id = 0;
  candidate_id parent_insert_candidate_id = 0;
  std::size_t delete_verified_partner_count = 1;
  std::size_t insert_verified_partner_count = 1;
  std::string identity_reason;
};

correspondence_decision classify_correspondence(
    const candidate_registry &registry, candidate_id del_id,
    candidate_id ins_id, match_kind match) {
  const move_candidate &deleted = registry.candidate(del_id);
  const move_candidate &inserted = registry.candidate(ins_id);
  correspondence_decision decision{
      del_id, ins_id, match,
      classify_movement(deleted.location, ancestor_summary(registry, deleted),
                        inserted.location, ancestor_summary(registry, inserted)),
  };
  if (match != match_kind::type1)
    decision.identity_reason = normalized_identity_reason(
        deleted, inserted, match == match_kind::type2);
  return decision;
}

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
    decisions.push_back(classify_correspondence(
        registry, del_id, ins_id, group.match));
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
        decision.match == match_kind::type1 ? "type1"
            : (decision.match == match_kind::type2 ? "type2c" : "type3"),
        decision.delete_verified_partner_count > 1 ||
                decision.insert_verified_partner_count > 1
            ? "competing_edges" : "one_to_one",
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
        decision.delete_verified_partner_count,
        decision.insert_verified_partner_count,
    });
    diagnostics.correspondences.back().identity_reason = decision.identity_reason;
  }
}

void update_correspondence_selection_results(
    const content_groups &groups, selection_diagnostics &diagnostics) {
  for (correspondence_diagnostic &correspondence :
       diagnostics.correspondences) {
    const match_kind expected_match =
        correspondence.correspondence_kind == "type1"
            ? match_kind::type1
            : (correspondence.correspondence_kind == "type2c"
                   ? match_kind::type2 : match_kind::type3);
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

// Exact identity alone cannot assign repeated endpoints. Use only original
// unique exact sibling pairs as independent context, and refine a balanced
// group only when every endpoint has a mutually unique supported partner.
std::vector<bool> refine_repeated_exact_groups(
    const candidate_registry &registry, std::vector<pending_group> &groups,
    std::vector<bool> &suppressed_aliases) {
  const candidate_id missing = std::numeric_limits<candidate_id>::max();
  using position = std::tuple<move_candidate::Kind, std::string, std::string,
                              std::size_t>;
  const auto reliable = [](const move_candidate &candidate) {
    return candidate.role == move_candidate::Role::structural_child &&
           candidate.sequence_context_reliable &&
           !candidate.sequence_parent_id.empty() &&
           !candidate.location.revision_file.empty() &&
           candidate.sequence_sibling_ordinal != 0 &&
           candidate.start_idx < candidate.end_idx;
  };
  std::vector<bool> refined_ids(registry.total_record_count(), false);
  suppressed_aliases.assign(registry.total_record_count(), false);
  const bool has_repeated_children = std::any_of(
      groups.begin(), groups.end(), [&](const pending_group &group) {
        return group.del_ids.size() > 1 &&
               group.del_ids.size() == group.ins_ids.size() &&
               std::all_of(group.del_ids.begin(), group.del_ids.end(),
                   [&](candidate_id id) { return reliable(registry.candidate(id)); }) &&
               std::all_of(group.ins_ids.begin(), group.ins_ids.end(),
                   [&](candidate_id id) { return reliable(registry.candidate(id)); });
      });
  if (!has_repeated_children) return refined_ids;
  const auto key = [](const move_candidate &candidate, std::size_t ordinal) {
    return position{candidate.kind, candidate.location.revision_file,
                    candidate.sequence_parent_id, ordinal};
  };
  std::map<position, candidate_id> positions;
  for (const pending_group &group : groups) {
    const auto index = [&](candidate_id id) {
      const move_candidate &candidate = registry.candidate(id);
      if (!reliable(candidate)) return;
      const auto inserted = positions.emplace(
          key(candidate, candidate.sequence_sibling_ordinal), id);
      if (!inserted.second && inserted.first->second != id)
        inserted.first->second = missing;
    };
    for (candidate_id id : group.del_ids) index(id);
    for (candidate_id id : group.ins_ids) index(id);
  }
  const auto lookup = [&](const move_candidate &candidate, int offset) {
    const std::size_t ordinal = candidate.sequence_sibling_ordinal;
    if ((offset < 0 && ordinal <= 1) ||
        (offset > 0 && ordinal == std::numeric_limits<std::size_t>::max()))
      return missing;
    const std::size_t wanted = offset < 0 ? ordinal - 1
                               : offset > 0 ? ordinal + 1 : ordinal;
    const auto found = positions.find(key(candidate, wanted));
    return found == positions.end() ? missing : found->second;
  };
  std::vector<candidate_id> seeds(registry.total_record_count(), missing);
  for (const pending_group &group : groups) {
    if (group.del_ids.size() != 1 || group.ins_ids.size() != 1) continue;
    const candidate_id del = group.del_ids.front(), ins = group.ins_ids.front();
    const auto &before = registry.candidate(del);
    const auto &after = registry.candidate(ins);
    if (reliable(before) && reliable(after) &&
        lookup(before, 0) == del && lookup(after, 0) == ins) {
      seeds[del] = ins;
      seeds[ins] = del;
    }
  }
  std::vector<candidate_id> inferred_partners(registry.total_record_count(), missing);
  std::vector<pending_group> refined;
  refined.reserve(groups.size());
  for (const pending_group &group : groups) {
    const std::size_t count = group.del_ids.size();
    bool eligible = count > 1 && count == group.ins_ids.size();
    const auto eligible_side = [&](const std::vector<candidate_id> &ids) {
      if (!std::all_of(ids.begin(), ids.end(), [&](candidate_id id) {
            const auto &candidate = registry.candidate(id);
            return reliable(candidate) && lookup(candidate, 0) == id;
          })) return false;
      std::vector<candidate_id> ordered = ids;
      const auto span_key = [&](candidate_id id) {
        const auto &candidate = registry.candidate(id);
        return std::tie(candidate.filename, candidate.start_idx, candidate.end_idx);
      };
      std::sort(ordered.begin(), ordered.end(), [&](candidate_id lhs, candidate_id rhs) {
        return span_key(lhs) < span_key(rhs);
      });
      for (std::size_t i = 1; i < ordered.size(); ++i) {
        if (candidates_overlap(registry.candidate(ordered[i - 1]),
                               registry.candidate(ordered[i]))) return false;
      }
      return true;
    };
    eligible = eligible && eligible_side(group.del_ids) && eligible_side(group.ins_ids);
    if (!eligible) {
      refined.push_back(group);
      continue;
    }
    std::unordered_map<candidate_id, std::size_t> insert_indices;
    for (std::size_t i = 0; i < count; ++i) insert_indices.emplace(group.ins_ids[i], i);
    struct best_partner {
      candidate_id id;
      int score = 0;
      bool tied = false;
    };
    std::vector<best_partner> delete_best(count, best_partner{missing});
    std::vector<best_partner> insert_best(count, best_partner{missing});
    const auto update = [](best_partner &best, candidate_id id, int score) {
      if (score > best.score) best = best_partner{id, score, false};
      else if (score == best.score && id != best.id) best.tied = true;
    };
    for (std::size_t i = 0; i < count; ++i) {
      const candidate_id del = group.del_ids[i];
      const auto &before = registry.candidate(del);
      // At most two nominations per source endpoint, rather than an NxM scan.
      std::vector<candidate_id> nominations;
      for (int offset : {-1, 1}) {
        const candidate_id neighbor = lookup(before, offset);
        if (neighbor == missing || seeds[neighbor] == missing) continue;
        const candidate_id nominee = lookup(registry.candidate(seeds[neighbor]), -offset);
        if (insert_indices.find(nominee) != insert_indices.end() &&
            std::find(nominations.begin(), nominations.end(), nominee) == nominations.end())
          nominations.push_back(nominee);
      }
      for (candidate_id ins : nominations) {
        const auto &after = registry.candidate(ins);
        int score = 0;
        bool contradiction = false;
        const auto inspect = [&](const move_candidate &source,
                                 const move_candidate &target, bool count_support) {
          for (int offset : {-1, 1}) {
            const candidate_id neighbor = lookup(source, offset);
            if (neighbor == missing || seeds[neighbor] == missing) continue;
            if (lookup(target, offset) != seeds[neighbor]) contradiction = true;
            else if (count_support) ++score;
          }
        };
        inspect(before, after, true);
        inspect(after, before, false);
        if (contradiction || score == 0) continue;
        update(delete_best[i], ins, score);
        update(insert_best[insert_indices.at(ins)], del, score);
      }
    }
    bool complete = true;
    for (std::size_t i = 0; i < count; ++i) {
      const auto &best = delete_best[i];
      if (best.id == missing || best.tied) {
        complete = false;
        break;
      }
      const auto &reverse = insert_best[insert_indices.at(best.id)];
      if (reverse.tied || reverse.id != group.del_ids[i]) {
        complete = false;
        break;
      }
    }
    if (!complete) {
      // Keep residual equivalence/copy meaning; elimination is not evidence.
      refined.push_back(group);
      continue;
    }
    for (std::size_t i = 0; i < count; ++i) {
      const candidate_id del = group.del_ids[i], ins = delete_best[i].id;
      refined.push_back(pending_group{group.content_hash, match_kind::type1, {del}, {ins}});
      refined_ids[del] = refined_ids[ins] = true;
      inferred_partners[del] = ins;
      inferred_partners[ins] = del;
    }
  }
  // Single-child diff wrappers alias their structural child. Mirror fully
  // established child partners so an unresolved wrapper equivalence group
  // cannot override identity or reopen a stationary child as a weaker move.
  using alias_key = std::tuple<move_candidate::Kind, std::string, std::size_t,
                               std::string>;
  const auto alias_position = [](const move_candidate &candidate) {
    return alias_key{candidate.kind, candidate.filename,
                     candidate.diff_region_start_idx, candidate.canonical_text};
  };
  std::map<alias_key, candidate_id> inferred_children;
  for (candidate_id id = 0; id < registry.total_record_count(); ++id) {
    if (inferred_partners[id] == missing) continue;
    const auto inserted = inferred_children.emplace(alias_position(registry.candidate(id)), id);
    if (!inserted.second) inserted.first->second = missing;
  }
  if (inferred_children.empty()) return refined_ids;
  const auto aliased_child = [&](candidate_id id) {
    const auto &wrapper = registry.candidate(id);
    if (wrapper.role != move_candidate::Role::single_child_wrapper) return missing;
    const auto found = inferred_children.find(alias_position(wrapper));
    if (found == inferred_children.end() || found->second == missing) return missing;
    const auto &child = registry.candidate(found->second);
    return wrapper.start_idx < child.start_idx && child.end_idx < wrapper.end_idx
               ? found->second : missing;
  };
  groups.clear();
  groups.reserve(refined.size());
  for (const pending_group &group : refined) {
    const auto contains_alias = [&](const std::vector<candidate_id> &ids) {
      return std::any_of(ids.begin(), ids.end(), [&](candidate_id id) {
        return aliased_child(id) != missing;
      });
    };
    if (!contains_alias(group.del_ids) && !contains_alias(group.ins_ids)) {
      groups.push_back(group);
      continue;
    }
    std::map<candidate_id, candidate_id> destination_wrappers;
    bool complete = !group.del_ids.empty() &&
                    group.del_ids.size() == group.ins_ids.size();
    for (candidate_id ins : group.ins_ids) {
      const candidate_id child = aliased_child(ins);
      if (child == missing || !destination_wrappers.emplace(child, ins).second) {
        complete = false;
        break;
      }
    }
    std::vector<std::pair<candidate_id, candidate_id>> partners;
    for (candidate_id del : group.del_ids) {
      if (!complete) break;
      const candidate_id child = aliased_child(del);
      const auto found = child == missing ? destination_wrappers.end()
                         : destination_wrappers.find(inferred_partners[child]);
      if (found == destination_wrappers.end()) {
        complete = false;
        break;
      }
      partners.emplace_back(del, found->second);
      destination_wrappers.erase(found);
    }
    if (!complete || !destination_wrappers.empty()) {
      // Unequal or incomplete wrapper coverage must not reopen already known
      // child identity. Genuine unequal structural groups never reach here.
      for (candidate_id id : group.del_ids) suppressed_aliases[id] = true;
      for (candidate_id id : group.ins_ids) suppressed_aliases[id] = true;
      groups.push_back(group);
      continue;
    }
    for (const auto &pair : partners) {
      groups.push_back(pending_group{group.content_hash, match_kind::type1,
                                    {pair.first}, {pair.second}});
      refined_ids[pair.first] = refined_ids[pair.second] = true;
    }
  }
  return refined_ids;
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
    const std::vector<type3_edge> &type3_edges,
    const std::vector<bool> &neighbor_refined,
    const std::vector<bool> &suppressed_aliases) {
  std::vector<match_proposal> proposals;

  for (const pending_group &group : exact_groups) {
    const auto suppressed_side = [&](const std::vector<candidate_id> &ids) {
      return std::any_of(ids.begin(), ids.end(),
                         [&](candidate_id id) { return suppressed_aliases[id]; });
    };
    if (!has_both_sides(group) || suppressed_side(group.del_ids) ||
        suppressed_side(group.ins_ids))
      continue;
    if (group.del_ids.size() == 1 && group.ins_ids.size() == 1) {
      const candidate_id del_id = group.del_ids.front();
      const candidate_id ins_id = group.ins_ids.front();
      proposals.push_back(make_pair_proposal(
          registry, del_id, ins_id, match_kind::type1,
          std::min(candidate_units(registry.candidate(del_id)),
                   candidate_units(registry.candidate(ins_id))),
          1000));
      if (neighbor_refined[del_id])
        proposals.back().selection_reason = "exact_neighbor_correspondence";
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

// Existential relocation evidence does not establish any individual partners.
// Retain two distinct source observations at most: any target either differs
// from the first, or (when source observations vary) from another source.
template <typename Project>
bool has_differing_group_observations(
    const candidate_registry &registry, const pending_group &group,
    Project project) {
  using observation = decltype(project(registry.candidate(group.del_ids.front()).location));
  observation first;
  bool varied = false;
  for (candidate_id id : group.del_ids) {
    const auto value = project(registry.candidate(id).location);
    if (!value) continue;
    if (!first) first = value;
    else if (*value != *first) varied = true;
  }
  if (!first) return false;
  for (candidate_id id : group.ins_ids) {
    const auto value = project(registry.candidate(id).location);
    if (value && (varied || *value != *first)) return true;
  }
  return false;
}

bool repeated_group_has_relocation_evidence(
    const candidate_registry &registry, const pending_group &group) {
  if (!has_both_sides(group)) return false;
  const auto file = [](const endpoint_location_context &context)
      -> std::optional<std::string_view> {
    if (context.revision_file.empty()) return std::nullopt;
    return context.revision_file;
  };
  if (has_differing_group_observations(registry, group, file)) return true;

  // With no differing file pair, all known files on opposite sides coincide.
  // Unknown-file endpoints cannot reach the classifier's container/anchor rules.
  const auto container = [](const endpoint_location_context &context)
      -> std::optional<std::string_view> {
    if (context.revision_file.empty() || !context.semantic_container_mapped)
      return std::nullopt;
    return context.semantic_container_id;
  };
  if (has_differing_group_observations(registry, group, container)) return true;

  // Similarly, no differing mapped-container pair means all eligible container
  // IDs coincide. Only reliable intervals in those mapped containers count.
  using interval = std::pair<std::string_view, std::string_view>;
  const auto anchors = [](const endpoint_location_context &context)
      -> std::optional<interval> {
    if (context.revision_file.empty() || !context.semantic_container_mapped ||
        !context.anchor_interval_reliable) return std::nullopt;
    return interval{context.previous_common_anchor_id,
                    context.next_common_anchor_id};
  };
  return has_differing_group_observations(registry, group, anchors);
}

void apply_correspondence_output_policy(
    const candidate_registry &registry,
    std::vector<match_proposal> &proposals,
    const std::vector<correspondence_decision> &decisions,
    grouping_profile_stats *stats) {
  for (match_proposal &proposal : proposals) {
    if (proposal.group.match == match_kind::type1 &&
        (proposal.group.del_ids.size() != 1 || proposal.group.ins_ids.size() != 1)) {
      if (!repeated_group_has_relocation_evidence(registry, proposal.group)) {
        proposal.disabled = true;
        if (stats != nullptr) ++stats->type1_policy_rejected;
      }
      continue;
    }
    if ((proposal.group.match != match_kind::type1 &&
         proposal.group.match != match_kind::type2 &&
         proposal.group.match != match_kind::type3) ||
        proposal.group.del_ids.size() != 1 ||
        proposal.group.ins_ids.size() != 1) {
      continue;
    }
    const correspondence_decision *decision = find_correspondence_decision(
        decisions, proposal.group.del_ids.front(),
        proposal.group.ins_ids.front());
    assert(decision != nullptr);
    if (decision != nullptr &&
        (!move_eligible(decision->classification) ||
         identity_rejected(decision->identity_reason))) {
      proposal.disabled = true;
      if (stats != nullptr && proposal.group.match == match_kind::type1) {
        ++stats->type1_policy_rejected;
      }
    }
  }
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
                  move_candidate::Kind              kind,
                  const std::vector<bool>           &type2_reserved) {
  std::vector<candidate_id> ids;
  for (std::size_t group_index : order) {
    const pending_group &group = exact_groups[group_index];
    if (has_both_sides(group)) {
      continue;
    }
    const std::vector<candidate_id> &side =
        kind == move_candidate::Kind::del ? group.del_ids : group.ins_ids;
    for (candidate_id id : side) {
      if (type2_reserved[id]) {
        continue;
      }
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
                  selection_diagnostics             *diagnostics,
                  const std::vector<bool>           &type2_reserved) {
  const std::vector<candidate_id> del_ids = collect_type3_ids(
      registry, exact_groups, order, move_candidate::Kind::del, type2_reserved);
  const std::vector<candidate_id> ins_ids = collect_type3_ids(
      registry, exact_groups, order, move_candidate::Kind::insert, type2_reserved);
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
              del_id, ins_id, "ambiguous_type2c", 0,
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

void collect_type2b_diagnostics(const candidate_registry &registry,
                               selection_diagnostics &diagnostics) {
  struct blind_group {
    type2b_group_diagnostic observation;
    // Count stronger consistent identities without expanding a Cartesian product.
    std::unordered_map<std::string, std::pair<std::size_t, std::size_t>> consistent;
  };
  std::unordered_map<std::string, blind_group> buckets;
  for (candidate_id id = 0; id < registry.total_record_count(); ++id) {
    if (!registry.is_active(id)) continue;
    const auto &candidate = registry.candidate(id);
    if (!candidate.type2_eligible || candidate.type2b_canonical_text.empty()) continue;
    std::string key = candidate.full_name;
    key.push_back('\0');
    key += candidate.type2b_canonical_text;
    auto &group = buckets[key];
    auto &counts = group.consistent[candidate.type2_canonical_text];
    if (candidate.kind == move_candidate::Kind::del) {
      group.observation.delete_candidate_ids.push_back(id);
      ++counts.first;
    } else {
      group.observation.insert_candidate_ids.push_back(id);
      ++counts.second;
    }
  }
  for (auto &entry : buckets) {
    auto &group = entry.second;
    auto &observation = group.observation;
    const auto inserts = observation.insert_candidate_ids.size();
    if (observation.delete_candidate_ids.empty() || inserts == 0) continue;
    for (const auto &identity : group.consistent) {
      observation.blind_only_pair_count +=
          identity.second.first * (inserts - identity.second.second);
    }
    // Pure exact/consistent groups add no blind-only correspondence evidence.
    if (observation.blind_only_pair_count == 0) continue;
    if (observation.delete_candidate_ids.size() == 1 && inserts == 1) {
      const auto &deleted = registry.candidate(observation.delete_candidate_ids[0]);
      const auto &inserted = registry.candidate(observation.insert_candidate_ids[0]);
      const auto classification = classify_movement(
          deleted.location, ancestor_summary(registry, deleted),
          inserted.location, ancestor_summary(registry, inserted));
      observation.location_change = std::string(to_string(classification.change_kind));
      observation.location_reason = std::string(to_string(classification.reason));
    }
    diagnostics.type2b_groups.push_back(std::move(observation));
  }
  std::sort(diagnostics.type2b_groups.begin(), diagnostics.type2b_groups.end(),
            [](const auto &a, const auto &b) {
              if (a.delete_candidate_ids != b.delete_candidate_ids)
                return a.delete_candidate_ids < b.delete_candidate_ids;
              return a.insert_candidate_ids < b.insert_candidate_ids;
            });
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
  std::vector<bool> neighbor_refined;
  std::vector<bool> suppressed_aliases;
  {
    scoped_profile_timer timer(profile, "content_groups.exact_build");
    exact_groups = build_exact_groups(registry);
    neighbor_refined = refine_repeated_exact_groups(registry, exact_groups,
                                                   suppressed_aliases);
    if (stats != nullptr) {
      stats->exact_groups_built = exact_groups.size();
    }
    decisions =
        classify_unique_correspondences(registry, exact_groups);
    classify_parent_carried_correspondences(registry, decisions);
  }

  std::vector<std::size_t> exact_group_order;
  {
    scoped_profile_timer timer(profile, "content_groups.exact_order");
    exact_group_order = group_selection_order(exact_groups, registry);
  }

  group_selection selection(registry.active_candidate_count());

  std::vector<pending_group> type2_groups;
  std::vector<bool> type2_reserved(registry.total_record_count(), false);
  {
    scoped_profile_timer timer(profile, "content_groups.type2c_build");
    type2_groups =
        build_type2_groups(registry, exact_groups, exact_group_order);
    if (stats != nullptr) {
      stats->type2_groups_built = type2_groups.size();
    }

    auto type2_decisions = classify_unique_correspondences(registry, type2_groups);
    // Reserve only unique normalized correspondences that pass the independent
    // identity gate, even when location evidence does not support reporting.
    // Reserve IDs only: distinct enclosing/descendant proposals still compete.
    for (const correspondence_decision &decision : type2_decisions) {
      if (identity_rejected(decision.identity_reason)) continue;
      type2_reserved[decision.delete_candidate_id] = true;
      type2_reserved[decision.insert_candidate_id] = true;
    }
    decisions.insert(decisions.end(), type2_decisions.begin(), type2_decisions.end());
  }

  order_correspondence_decisions(decisions);

  std::vector<type3_edge> type3_edges;
  {
    scoped_profile_timer timer(profile, "content_groups.type3_build");
    type3_edges =
        build_type3_edges(registry, exact_groups, exact_group_order, stats,
                          diagnostics, type2_reserved);
  }

  // Content similarity establishes possible correspondence, not relocation.
  // Classify every verified edge before selection in every output mode. Keep
  // competing partners visible; do not infer carrying from an edited parent.
  std::vector<std::size_t> partner_counts(registry.total_record_count(), 0);
  for (const type3_edge &edge : type3_edges) {
    ++partner_counts[edge.del_id];
    ++partner_counts[edge.ins_id];
  }
  for (const type3_edge &edge : type3_edges) {
    auto decision = classify_correspondence(
        registry, edge.del_id, edge.ins_id, match_kind::type3);
    decision.delete_verified_partner_count = partner_counts[edge.del_id];
    decision.insert_verified_partner_count = partner_counts[edge.ins_id];
    decisions.push_back(std::move(decision));
  }
  order_correspondence_decisions(decisions);

  {
    scoped_profile_timer timer(profile, "content_groups.unified_select");
    std::vector<match_proposal> proposals = build_match_proposals(
        registry, exact_groups, type2_groups, type3_edges, neighbor_refined,
        suppressed_aliases);
    apply_correspondence_output_policy(registry, proposals, decisions, stats);
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
    {
      scoped_profile_timer timer(profile, "content_groups.type2b_diagnostics");
      collect_type2b_diagnostics(registry, *diagnostics);
      if (profile != nullptr)
        profile->add_counter("content_groups.type2b_groups_observed",
                             diagnostics->type2b_groups.size());
    }
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
    profile->add_counter("content_groups.type2c_groups_built",
                         profile_stats.type2_groups_built);
    profile->add_counter("content_groups.type2c_groups_selected",
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
  }

  return out;
}

} // namespace srcmove
