// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file content_group_builder.cpp
 */

#include "content_group_builder.hpp"
#include "move_candidate.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_groups.hpp"

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

struct pending_group {
  std::uint64_t              content_hash = 0;
  match_kind                 match = match_kind::unmatched;
  std::vector<candidate_id>  del_ids;
  std::vector<candidate_id>  ins_ids;
};

bool has_both_sides(const pending_group &group) {
  return !group.del_ids.empty() && !group.ins_ids.empty();
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

std::vector<candidate_id>
filter_unused_ids(const std::vector<candidate_id>      &ids,
                  const std::unordered_set<candidate_id> &used_ids) {
  std::vector<candidate_id> out;
  out.reserve(ids.size());

  for (candidate_id id : ids) {
    if (used_ids.find(id) == used_ids.end()) {
      out.push_back(id);
    }
  }

  return out;
}

} // namespace

content_groups build_content_groups(const candidate_registry &registry,
                                    bool confirm_text_equality) {
  content_groups out;

  const std::unordered_map<std::uint64_t, bucket_ids> &hash_buckets =
      registry.hash_buckets();
  out.reserve_groups(hash_buckets.size());

  if (!confirm_text_equality) {
    for (const std::pair<const std::uint64_t, bucket_ids> &kv : hash_buckets) {
      const match_kind match =
          (!kv.second.del_ids.empty() && !kv.second.ins_ids.empty())
              ? match_kind::exact
              : match_kind::unmatched;
      add_group(out, kv.first, kv.second.del_ids, kv.second.ins_ids, match);
    }
    return out;
  }

  static const std::vector<candidate_id> kEmpty;
  std::vector<pending_group> exact_groups;
  exact_groups.reserve(hash_buckets.size());

  for (const auto &kv : hash_buckets) {
    const std::uint64_t content_hash = kv.first;
    const bucket_ids   &bucket       = kv.second;

    std::unordered_map<std::string_view, std::vector<candidate_id>, sv_hash>
        del_by_text;
    std::unordered_map<std::string_view, std::vector<candidate_id>, sv_hash>
        ins_by_text;

    del_by_text.reserve(bucket.del_ids.size());
    ins_by_text.reserve(bucket.ins_ids.size());

    for (candidate_id id : bucket.del_ids) {
      const candidate_registry::candidate_record &record = registry.record(id);
      if (!record.active) {
        continue;
      }
      const move_candidate &candidate = record.candidate;
      del_by_text[std::string_view(candidate.canonical_text)].push_back(id);
    }

    for (candidate_id id : bucket.ins_ids) {
      const candidate_registry::candidate_record &record = registry.record(id);
      if (!record.active) {
        continue;
      }
      const move_candidate &candidate = record.candidate;
      ins_by_text[std::string_view(candidate.canonical_text)].push_back(id);
    }

    std::unordered_map<std::string_view, bool, sv_hash> seen;
    seen.reserve(del_by_text.size() + ins_by_text.size());

    for (auto &entry : del_by_text) {
      std::string_view           text = entry.first;
      std::vector<unsigned int> &dels = entry.second;

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
      std::string_view           text = entry.first;
      std::vector<unsigned int> &inss = entry.second;

      if (seen.find(text) != seen.end()) {
        continue;
      }

      exact_groups.push_back(
          pending_group{content_hash, match_kind::unmatched, kEmpty, inss});
    }
  }

  std::unordered_set<candidate_id> used_ids;
  used_ids.reserve(registry.active_candidate_count());

  for (const pending_group &group : exact_groups) {
    if (!has_both_sides(group)) {
      continue;
    }

    add_pending_group(out, group);
    mark_ids_used(group, used_ids);
  }

  std::unordered_map<std::string_view, pending_group, sv_hash> type2_groups;
  type2_groups.reserve(exact_groups.size());

  for (const pending_group &group : exact_groups) {
    if (has_both_sides(group)) {
      continue;
    }

    for (candidate_id id : group.del_ids) {
      if (used_ids.find(id) != used_ids.end()) {
        continue;
      }

      const move_candidate &candidate = registry.candidate(id);
      pending_group &type2_group =
          type2_groups[std::string_view(candidate.type2_canonical_text)];
      type2_group.content_hash = candidate.type2_hash;
      type2_group.match = match_kind::type2;
      type2_group.del_ids.push_back(id);
    }

    for (candidate_id id : group.ins_ids) {
      if (used_ids.find(id) != used_ids.end()) {
        continue;
      }

      const move_candidate &candidate = registry.candidate(id);
      pending_group &type2_group =
          type2_groups[std::string_view(candidate.type2_canonical_text)];
      type2_group.content_hash = candidate.type2_hash;
      type2_group.match = match_kind::type2;
      type2_group.ins_ids.push_back(id);
    }
  }

  for (const auto &entry : type2_groups) {
    const pending_group &group = entry.second;
    if (!has_both_sides(group)) {
      continue;
    }

    add_pending_group(out, group);
    mark_ids_used(group, used_ids);
  }

  for (const pending_group &group : exact_groups) {
    if (has_both_sides(group)) {
      continue;
    }

    std::vector<candidate_id> del_ids = filter_unused_ids(group.del_ids, used_ids);
    std::vector<candidate_id> ins_ids = filter_unused_ids(group.ins_ids, used_ids);
    if (del_ids.empty() && ins_ids.empty()) {
      continue;
    }

    add_group(out, group.content_hash, del_ids, ins_ids, match_kind::unmatched);
  }

#ifndef NDEBUG
  for (const content_group &g : out.groups()) {
    assert(g.del_count() + g.ins_count() > 0);
  }
#endif

  return out;
}

} // namespace srcmove
