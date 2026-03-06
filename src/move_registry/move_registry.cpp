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

void move_registry::clear() {
  deletes_.clear();
  inserts_.clear();
  buckets_by_hash_.clear();
  groups_.clear();
}

void move_registry::reserve(std::size_t expected_deletes,
                            std::size_t expected_inserts) {
  deletes_.reserve(expected_deletes);
  inserts_.reserve(expected_inserts);

  // Hash bucket count is data-dependent, but reserving a rough upper bound
  // helps avoid rehashing during ingestion.
  buckets_by_hash_.reserve(expected_deletes + expected_inserts);
}

move_registry::id_t move_registry::add_delete(move_candidate del) {
  const id_t id = static_cast<id_t>(deletes_.size());
  const std::uint64_t h = del.hash;

  deletes_.push_back(std::move(del));
  auto &bucket = buckets_by_hash_[h];
  bucket.del_ids.push_back(id);
  return id;
}

move_registry::id_t move_registry::add_insert(move_candidate ins) {
  const id_t id = static_cast<id_t>(inserts_.size());
  const std::uint64_t h = ins.hash;

  inserts_.push_back(std::move(ins));
  auto &bucket = buckets_by_hash_[h];
  bucket.ins_ids.push_back(id);
  return id;
}

void move_registry::build_groups(bool confirm_text_equality) {
  // Group building is intentionally delegated to a separate module.
  groups_ = build_groups_from_buckets(deletes_, inserts_, buckets_by_hash_,
                                      confirm_text_equality);
}

move_registry::id_view
move_registry::group_delete_ids(const content_group_compact &g) const noexcept {
  const std::uint32_t n = g.del_end - g.del_begin;
  if (n == 0)
    return id_view{nullptr, 0};

  return id_view{&groups_.group_del_ids[g.del_begin],
                 static_cast<std::size_t>(n)};
}

move_registry::id_view
move_registry::group_insert_ids(const content_group_compact &g) const noexcept {
  const std::uint32_t n = g.ins_end - g.ins_begin;
  if (n == 0)
    return id_view{nullptr, 0};

  return id_view{&groups_.group_ins_ids[g.ins_begin],
                 static_cast<std::size_t>(n)};
}

move_registry build_move_registry(std::vector<move_candidate> &candidates) {

  move_registry mr;
  mr.reserve(/*expected_deletes=*/candidates.size(),
             /*expected_inserts=*/candidates.size());

  // Feed registry from collected regions
  for (auto &r : candidates) {
    if (r.kind == move_candidate::Kind::del) {
      mr.add_delete(std::move(r));
    } else {
      mr.add_insert(std::move(r));
    }
  }

  // Build groups (does equality confirmation + dedupe grouping if enabled)
  mr.build_groups(/*confirm_text_equality=*/true);
  return mr;
}

} // namespace srcmove
