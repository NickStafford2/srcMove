// src/move_groups_builder.cpp
// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_groups_builder.cpp
 */
#include "move_groups_builder.hpp"

#include <cassert>
#include <string_view>
#include <unordered_map>
#include <utility>

namespace srcmove {

static group_kind classify_counts(std::size_t del_count,
                                  std::size_t ins_count) {
  if (del_count == 0 && ins_count == 0) {
    // A correctly-constructed group should never be empty on both sides.
    return group_kind::ambiguous;
  }
  if (del_count > 0 && ins_count == 0)
    return group_kind::delete_only;
  if (del_count == 0 && ins_count > 0)
    return group_kind::insert_only;

  // Both sides exist.
  if (del_count == 1 && ins_count == 1)
    return group_kind::move_1_to_1;

  if (del_count == ins_count && del_count > 1)
    return group_kind::moves_many;

  // If inserts exceed deletes, it might be copy/paste or repeated insertion.
  // If deletes exceed inserts, it might be multiple removals with one
  // remaining.
  return group_kind::copy_or_repeat;
}

static void add_group(content_group_storage &out, std::uint64_t content_hash,
                      const std::vector<candidate_id> &del_ids,
                      const std::vector<candidate_id> &ins_ids) {
  const std::uint32_t group_id = static_cast<std::uint32_t>(out.groups.size());

  const std::uint32_t del_begin =
      static_cast<std::uint32_t>(out.group_del_ids.size());
  out.group_del_ids.insert(out.group_del_ids.end(), del_ids.begin(),
                           del_ids.end());
  const std::uint32_t del_end =
      static_cast<std::uint32_t>(out.group_del_ids.size());

  const std::uint32_t ins_begin =
      static_cast<std::uint32_t>(out.group_ins_ids.size());
  out.group_ins_ids.insert(out.group_ins_ids.end(), ins_ids.begin(),
                           ins_ids.end());
  const std::uint32_t ins_end =
      static_cast<std::uint32_t>(out.group_ins_ids.size());

  const group_kind kind = classify_counts(del_ids.size(), ins_ids.size());

  out.groups.push_back(content_group_compact{
      content_hash,
      group_id,
      del_begin,
      del_end,
      ins_begin,
      ins_end,
      kind,
  });
}

content_group_storage build_groups_from_buckets(
    const std::vector<move_candidate> &deletes,
    const std::vector<move_candidate> &inserts,
    const std::unordered_map<std::uint64_t, bucket_ids> &by_hash,
    bool confirm_text_equality) {

  content_group_storage out;
  out.groups.reserve(by_hash.size());

  // Fast path: one group per hash bucket.
  if (!confirm_text_equality) {
    for (const auto &kv : by_hash) {
      const auto h = kv.first;
      const auto &bucket = kv.second;
      add_group(out, h, bucket.del_ids, bucket.ins_ids);
    }
    return out;
  }

  // confirm_text_equality == true:
  // Split each hash bucket into subgroups by exact full_text.
  //
  // Key on std::string_view referencing candidates' stored full_text.
  // Safe because deletes/inserts own the strings for the lifetime of the
  // registry build.
  struct sv_hash {
    std::size_t operator()(std::string_view s) const noexcept {
      return std::hash<std::string_view>{}(s);
    }
  };

  static const std::vector<candidate_id> kEmpty;

  for (const auto &kv : by_hash) {
    const auto h = kv.first;
    const auto &bucket = kv.second;

    std::unordered_map<std::string_view, std::vector<candidate_id>, sv_hash>
        del_by_text;
    std::unordered_map<std::string_view, std::vector<candidate_id>, sv_hash>
        ins_by_text;

    del_by_text.reserve(bucket.del_ids.size());
    ins_by_text.reserve(bucket.ins_ids.size());

    for (candidate_id did : bucket.del_ids) {
      const auto &d = deletes[did];
      del_by_text[std::string_view(d.full_text)].push_back(did);
    }
    for (candidate_id iid : bucket.ins_ids) {
      const auto &ins = inserts[iid];
      ins_by_text[std::string_view(ins.full_text)].push_back(iid);
    }

    // Union of keys: build groups for each distinct exact text.
    std::unordered_map<std::string_view, bool, sv_hash> seen;
    seen.reserve(del_by_text.size() + ins_by_text.size());

    // Build groups for delete keys first.
    for (auto &kv_del : del_by_text) {
      std::string_view text = kv_del.first;
      auto &dels = kv_del.second;

      (void)seen.emplace(text, true);

      auto it = ins_by_text.find(text);
      if (it != ins_by_text.end()) {
        add_group(out, h, dels, it->second);
      } else {
        add_group(out, h, dels, kEmpty);
      }
    }

    // Then groups for insert-only keys.
    for (auto &kv_ins : ins_by_text) {
      std::string_view text = kv_ins.first;
      auto &inss = kv_ins.second;

      if (seen.find(text) != seen.end())
        continue;
      add_group(out, h, kEmpty, inss);
    }
  }

#ifndef NDEBUG
  for (const auto &g : out.groups) {
    assert(g.del_count() + g.ins_count() > 0);
  }
#endif

  return out;
}

} // namespace srcmove
