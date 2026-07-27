// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file content_group_builder.cpp
 */

#include "content_group_builder.hpp"
#include "move_candidate.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_groups.hpp"

#include <algorithm>
#include <cassert>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
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
  key.push_back(candidate.role == move_candidate::Role::structural_child ? 's'
                                                                         : 'd');
  return key;
}

struct pending_group {
  std::uint64_t             content_hash = 0;
  match_kind                match        = match_kind::unmatched;
  std::vector<candidate_id> del_ids;
  std::vector<candidate_id> ins_ids;
};

struct covered_span {
  move_candidate::Kind kind = move_candidate::Kind::del;
  std::string_view     filename;
  std::size_t          start_idx = 0;
  std::size_t          end_idx   = 0;
};

struct selection_state {
  explicit selection_state(std::size_t candidate_count) {
    used_ids.reserve(candidate_count);
    covered.reserve(candidate_count);
  }

  std::unordered_set<candidate_id> used_ids;
  std::vector<covered_span>        covered;
};

bool has_both_sides(const pending_group &group) {
  return !group.del_ids.empty() && !group.ins_ids.empty();
}

bool is_one_to_one(const pending_group &group) {
  return group.del_ids.size() == 1 && group.ins_ids.size() == 1;
}

void add_pending_group(content_groups &out, const pending_group &group) {
  add_group(out, group.content_hash, group.del_ids, group.ins_ids, group.match);
}

void mark_ids_used(const pending_group              &group,
                   std::unordered_set<candidate_id> &used_ids) {
  if (!has_both_sides(group)) {
    return;
  }

  used_ids.insert(group.del_ids.begin(), group.del_ids.end());
  used_ids.insert(group.ins_ids.begin(), group.ins_ids.end());
}

bool contains_span(const covered_span &outer, const move_candidate &candidate) {
  return outer.kind == candidate.kind && outer.filename == candidate.filename &&
         outer.start_idx <= candidate.start_idx &&
         candidate.end_idx <= outer.end_idx;
}

bool candidate_contains_span(const move_candidate &candidate,
                             const covered_span   &inner) {
  return inner.kind == candidate.kind && inner.filename == candidate.filename &&
         candidate.start_idx <= inner.start_idx &&
         inner.end_idx <= candidate.end_idx;
}

void mark_group_covered(const pending_group       &group,
                        const candidate_registry  &registry,
                        std::vector<covered_span> &covered) {
  if (!has_both_sides(group)) {
    return;
  }

  for (candidate_id id : group.del_ids) {
    const move_candidate &candidate = registry.candidate(id);
    covered.push_back(covered_span{candidate.kind, candidate.filename,
                                   candidate.start_idx, candidate.end_idx});
  }

  for (candidate_id id : group.ins_ids) {
    const move_candidate &candidate = registry.candidate(id);
    covered.push_back(covered_span{candidate.kind, candidate.filename,
                                   candidate.start_idx, candidate.end_idx});
  }
}

void add_selected_group(content_groups           &out,
                        const pending_group      &group,
                        const candidate_registry &registry,
                        selection_state          &state) {
  add_pending_group(out, group);
  mark_ids_used(group, state.used_ids);
  mark_group_covered(group, registry, state.covered);
}

bool candidate_is_suppressed(const move_candidate            &candidate,
                             const std::vector<covered_span> &covered) {
  for (const covered_span &span : covered) {
    if (contains_span(span, candidate)) {
      return true;
    }

    if (candidate.role != move_candidate::Role::structural_child &&
        candidate_contains_span(candidate, span)) {
      return true;
    }
  }

  return false;
}

bool group_is_suppressed(const pending_group             &group,
                         const candidate_registry        &registry,
                         const std::vector<covered_span> &covered) {
  if (!has_both_sides(group)) {
    return false;
  }

  for (candidate_id id : group.del_ids) {
    if (!candidate_is_suppressed(registry.candidate(id), covered)) {
      return false;
    }
  }

  for (candidate_id id : group.ins_ids) {
    if (!candidate_is_suppressed(registry.candidate(id), covered)) {
      return false;
    }
  }

  return true;
}

std::size_t candidate_span_size(const move_candidate &candidate) {
  if (candidate.end_idx < candidate.start_idx) {
    return 0;
  }
  return candidate.end_idx - candidate.start_idx + 1;
}

std::size_t group_span_size(const pending_group      &group,
                            const candidate_registry &registry) {
  std::size_t size = 0;

  for (candidate_id id : group.del_ids) {
    size += candidate_span_size(registry.candidate(id));
  }

  for (candidate_id id : group.ins_ids) {
    size += candidate_span_size(registry.candidate(id));
  }

  return size;
}

candidate_id min_group_id(const pending_group &group) {
  candidate_id min_id = static_cast<candidate_id>(-1);

  for (candidate_id id : group.del_ids) {
    min_id = std::min(min_id, id);
  }

  for (candidate_id id : group.ins_ids) {
    min_id = std::min(min_id, id);
  }

  return min_id;
}

bool any_single_child_wrapper(const pending_group      &group,
                              const candidate_registry &registry) {
  for (candidate_id id : group.del_ids) {
    const move_candidate &candidate = registry.candidate(id);
    if (candidate.role == move_candidate::Role::single_child_wrapper) {
      return true;
    }
  }

  for (candidate_id id : group.ins_ids) {
    const move_candidate &candidate = registry.candidate(id);
    if (candidate.role == move_candidate::Role::single_child_wrapper) {
      return true;
    }
  }

  return false;
}

enum class group_priority : int {
  normal               = 1,
  single_child_wrapper = 2,
};

group_priority group_source_priority(const pending_group      &group,
                                     const candidate_registry &registry) {
  if (any_single_child_wrapper(group, registry)) {
    return group_priority::single_child_wrapper;
  }
  return group_priority::normal;
}

bool group_priority_less(const pending_group      &lhs,
                         const pending_group      &rhs,
                         const candidate_registry &registry) {
  const group_priority lhs_source = group_source_priority(lhs, registry);
  const group_priority rhs_source = group_source_priority(rhs, registry);
  if (lhs_source != rhs_source) {
    return lhs_source < rhs_source;
  }

  const std::size_t lhs_size = group_span_size(lhs, registry);
  const std::size_t rhs_size = group_span_size(rhs, registry);
  if (lhs_size != rhs_size) {
    return lhs_size > rhs_size;
  }

  return min_group_id(lhs) < min_group_id(rhs);
}

std::vector<candidate_id>
filter_unused_ids(const std::vector<candidate_id>        &ids,
                  const std::unordered_set<candidate_id> &used_ids,
                  const candidate_registry               &registry,
                  const std::vector<covered_span>        &covered) {
  std::vector<candidate_id> out;
  out.reserve(ids.size());

  for (candidate_id id : ids) {
    const move_candidate &candidate = registry.candidate(id);
    if (candidate.role == move_candidate::Role::single_child_wrapper ||
        candidate.role == move_candidate::Role::multi_child_wrapper) {
      continue;
    }
    if (used_ids.find(id) == used_ids.end() &&
        !candidate_is_suppressed(candidate, covered)) {
      out.push_back(id);
    }
  }

  return out;
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

std::vector<pending_group>
build_exact_groups(const candidate_registry &registry) {
  static const std::vector<candidate_id> kEmpty;

  const std::unordered_map<std::uint64_t, bucket_ids> &hash_buckets =
      registry.hash_buckets();
  std::vector<pending_group> exact_groups;
  exact_groups.reserve(hash_buckets.size());

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
                               selection_state            &state) {
  std::sort(exact_groups.begin(), exact_groups.end(),
            [&registry](const pending_group &lhs, const pending_group &rhs) {
              return group_priority_less(lhs, rhs, registry);
            });

  for (const pending_group &group : exact_groups) {
    if (!has_both_sides(group)) {
      continue;
    }
    if (group_is_suppressed(group, registry, state.covered)) {
      continue;
    }

    add_selected_group(out, group, registry, state);
  }
}

using type2_group_map =
    std::unordered_map<std::string_view, pending_group, sv_hash>;

type2_group_map
build_type2_groups(const candidate_registry         &registry,
                   const std::vector<pending_group> &exact_groups,
                   const selection_state            &state) {
  type2_group_map type2_groups;
  type2_groups.reserve(exact_groups.size());

  for (const pending_group &group : exact_groups) {
    if (has_both_sides(group)) {
      continue;
    }

    for (candidate_id id : group.del_ids) {
      if (state.used_ids.find(id) != state.used_ids.end()) {
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
      if (state.used_ids.find(id) != state.used_ids.end()) {
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
                               selection_state          &state) {
  for (const auto &entry : type2_groups) {
    const pending_group &group = entry.second;
    if (!is_one_to_one(group)) {
      continue;
    }
    if (group_is_suppressed(group, registry, state.covered)) {
      continue;
    }

    add_selected_group(out, group, registry, state);
  }
}

void add_unmatched_exact_groups(content_groups                   &out,
                                const candidate_registry         &registry,
                                const std::vector<pending_group> &exact_groups,
                                const selection_state            &state) {
  for (const pending_group &group : exact_groups) {
    if (has_both_sides(group)) {
      continue;
    }

    std::vector<candidate_id> del_ids = filter_unused_ids(
        group.del_ids, state.used_ids, registry, state.covered);
    std::vector<candidate_id> ins_ids = filter_unused_ids(
        group.ins_ids, state.used_ids, registry, state.covered);
    if (del_ids.empty() && ins_ids.empty()) {
      continue;
    }

    add_group(out, group.content_hash, del_ids, ins_ids, match_kind::unmatched);
  }
}

} // namespace

content_groups build_content_groups(const candidate_registry &registry,
                                    bool confirm_text_equality) {
  content_groups out;
  out.reserve_groups(registry.hash_buckets().size());

  if (!confirm_text_equality) {
    add_hash_bucket_groups(out, registry);
    return out;
  }

  std::vector<pending_group> exact_groups = build_exact_groups(registry);
  selection_state            state(registry.active_candidate_count());

  add_selected_exact_groups(out, registry, exact_groups, state);

  type2_group_map type2_groups =
      build_type2_groups(registry, exact_groups, state);
  add_selected_type2_groups(out, registry, type2_groups, state);

  add_unmatched_exact_groups(out, registry, exact_groups, state);

#ifndef NDEBUG
  for (const content_group &g : out.groups()) {
    assert(g.del_count() + g.ins_count() > 0);
  }
#endif

  return out;
}

} // namespace srcmove
