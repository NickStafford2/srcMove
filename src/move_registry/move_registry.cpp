// src/move_registry.cpp
// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_registry.cpp
 */
#include "move_registry.hpp"

#include <cassert>
#include <utility>

#include "move_groups_builder.hpp"

namespace srcmove {

void grouped_candidates::clear() {
  deletes_.clear();
  inserts_.clear();
  hash_index_.clear();
  groups_.clear();
}

void grouped_candidates::reserve(std::size_t expected_deletes,
                                 std::size_t expected_inserts) {
  deletes_.reserve(expected_deletes);
  inserts_.reserve(expected_inserts);

  // Hash bucket count is data-dependent, but reserving a rough upper bound
  // helps avoid rehashing during ingestion.
  hash_index_.reserve(expected_deletes + expected_inserts);
}

grouped_candidates::id_t grouped_candidates::add_delete(move_candidate del) {
  const id_t id = static_cast<id_t>(deletes_.size());
  const std::uint64_t h = del.hash;

  deletes_.push_back(std::move(del));
  auto &bucket = hash_index_[h];
  bucket.del_ids.push_back(id);
  return id;
}

grouped_candidates::id_t grouped_candidates::add_insert(move_candidate ins) {
  const id_t id = static_cast<id_t>(inserts_.size());
  const std::uint64_t h = ins.hash;

  inserts_.push_back(std::move(ins));
  auto &bucket = hash_index_[h];
  bucket.ins_ids.push_back(id);
  return id;
}

void grouped_candidates::finalize_groups(bool confirm_text_equality) {
  // Group building is intentionally delegated to a separate module.
  groups_ = build_groups_from_buckets(deletes_, inserts_, hash_index_,
                                      confirm_text_equality);
}

grouped_candidates::id_view grouped_candidates::group_delete_ids(
    const content_group_compact &g) const noexcept {
  const std::uint32_t n = g.del_end - g.del_begin;
  if (n == 0)
    return id_view{nullptr, 0};

  return id_view{&groups_.group_del_ids[g.del_begin],
                 static_cast<std::size_t>(n)};
}

grouped_candidates::id_view grouped_candidates::group_insert_ids(
    const content_group_compact &g) const noexcept {
  const std::uint32_t n = g.ins_end - g.ins_begin;
  if (n == 0)
    return id_view{nullptr, 0};

  return id_view{&groups_.group_ins_ids[g.ins_begin],
                 static_cast<std::size_t>(n)};
}

grouped_candidates
grouped_candidates::from_candidates(std::vector<move_candidate> candidates,
                                    bool confirm_text_equality) {
  grouped_candidates mr;
  mr.reserve(candidates.size(), candidates.size());

  for (auto &c : candidates) {
    if (c.kind == move_candidate::Kind::del)
      mr.add_delete(std::move(c));
    else
      mr.add_insert(std::move(c));
  }

  mr.finalize_groups(confirm_text_equality);
  return mr;
}

} // namespace srcmove
