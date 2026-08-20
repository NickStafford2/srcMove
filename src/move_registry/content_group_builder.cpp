// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file content_group_builder.cpp
 */

#include "content_group_builder.hpp"
#include "move_candidate.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_groups.hpp"
#include "move_registry/group_selection.hpp"
#include "profile.hpp"

#include <algorithm>
#include <cassert>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace srcmove {

namespace {

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
               match_kind                       match) {
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
            ? match_kind::exact
            : match_kind::unmatched;
    add_group(out, kv.first, kv.second.del_ids, kv.second.ins_ids, match);
  }
}

void add_selected_group(content_groups           &out,
                        const candidate_registry &registry,
                        const pending_group      &group,
                        group_selection          &selection) {
  add_group(out, group.content_hash, group.del_ids, group.ins_ids, group.match);
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
            pending_group{content_hash, match_kind::exact, dels, it->second});
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

void add_selected_exact_groups(content_groups             &out,
                               const candidate_registry   &registry,
                               std::vector<pending_group> &exact_groups,
                               group_selection            &selection) {
  // Current sort comparisons rescan group ids for tier/span/min-id keys:
  // O(G log G * K), where K is average ids per compared group. See the
  // precompute-selection-key note before optimizing this.
  std::sort(exact_groups.begin(), exact_groups.end(),
            [&registry](const pending_group &lhs, const pending_group &rhs) {
              return group_selection_order_less(lhs, rhs, registry);
            });

  for (const pending_group &group : exact_groups) {
    if (!has_both_sides(group)) {
      continue;
    }
    if (selection.group_is_fully_suppressed(group, registry)) {
      continue;
    }

    add_selected_group(out, registry, group, selection);
  }
}

using type2_group_map =
    std::unordered_map<std::string_view, pending_group, sv_hash>;

type2_group_map
build_type2_groups(const candidate_registry         &registry,
                   const std::vector<pending_group> &exact_groups,
                   const group_selection            &selection) {
  type2_group_map type2_groups;
  type2_groups.reserve(exact_groups.size());

  // O(unmatched exact-group ids). Type-2 candidates are grouped by their
  // already-computed identifier-normalized canonical text.
  for (const pending_group &group : exact_groups) {
    if (has_both_sides(group)) {
      continue;
    }

    for (candidate_id id : group.del_ids) {
      if (selection.id_is_used(id)) {
        continue;
      }

      const move_candidate &candidate = registry.candidate(id);
      if (!candidate.type2_eligible) {
        continue;
      }
      pending_group &type2_group =
          type2_groups[std::string_view(candidate.type2_canonical_text)];
      type2_group.content_hash = candidate.type2_hash;
      type2_group.match        = match_kind::type2;
      type2_group.del_ids.push_back(id);
    }

    for (candidate_id id : group.ins_ids) {
      if (selection.id_is_used(id)) {
        continue;
      }

      const move_candidate &candidate = registry.candidate(id);
      if (!candidate.type2_eligible) {
        continue;
      }
      pending_group &type2_group =
          type2_groups[std::string_view(candidate.type2_canonical_text)];
      type2_group.content_hash = candidate.type2_hash;
      type2_group.match        = match_kind::type2;
      type2_group.ins_ids.push_back(id);
    }
  }

  return type2_groups;
}

void add_selected_type2_groups(content_groups           &out,
                               const candidate_registry &registry,
                               const type2_group_map    &type2_groups,
                               group_selection          &selection) {
  for (const auto &entry : type2_groups) {
    const pending_group &group = entry.second;
    if (!is_one_to_one(group)) {
      continue;
    }
    if (selection.group_is_fully_suppressed(group, registry)) {
      continue;
    }

    add_selected_group(out, registry, group, selection);
  }
}

void add_unmatched_exact_groups(content_groups                   &out,
                                const candidate_registry         &registry,
                                const std::vector<pending_group> &exact_groups,
                                const group_selection            &selection) {
  // O(unmatched exact-group ids * covered spans) in the worst case because
  // suppression checks scan selected covered spans.
  for (const pending_group &group : exact_groups) {
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
                                    profile_report *profile) {
  scoped_profile_timer total_timer(profile, "content_groups.total");

  content_groups out;
  out.reserve_groups(registry.hash_buckets().size());

  if (mode == content_grouping_mode::hash_bucket_only) {
    scoped_profile_timer timer(profile, "content_groups.hash_bucket_only");
    add_hash_bucket_groups(out, registry);
    return out;
  }

  std::vector<pending_group> exact_groups;
  {
    scoped_profile_timer timer(profile, "content_groups.exact_build");
    exact_groups = build_exact_groups(registry);
  }

  group_selection            selection(registry.active_candidate_count());

  {
    scoped_profile_timer timer(profile, "content_groups.exact_select");
    add_selected_exact_groups(out, registry, exact_groups, selection);
  }

  type2_group_map type2_groups;
  {
    scoped_profile_timer timer(profile, "content_groups.type2_build");
    type2_groups = build_type2_groups(registry, exact_groups, selection);
  }

  {
    scoped_profile_timer timer(profile, "content_groups.type2_select");
    add_selected_type2_groups(out, registry, type2_groups, selection);
  }

  {
    scoped_profile_timer timer(profile, "content_groups.unmatched_emit");
    add_unmatched_exact_groups(out, registry, exact_groups, selection);
  }

#ifndef NDEBUG
  for (const content_group &g : out.groups()) {
    assert(g.del_count() + g.ins_count() > 0);
  }
#endif

  return out;
}

} // namespace srcmove
