// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file grouped_candidates_builder.cpp
 */

#include <cassert>
#include <utility>

#include "grouped_candidates.hpp"
#include "grouped_candidates_builder.hpp"
#include "move_groups_builder.hpp"
#include "move_registry/move_groups.hpp"

namespace srcmove {

void grouped_candidates_builder::clear() {
  deletes_.clear();
  inserts_.clear();
  hash_index_.clear();
}

void grouped_candidates_builder::reserve(std::size_t expected_deletes,
                                         std::size_t expected_inserts) {
  deletes_.reserve(expected_deletes);
  inserts_.reserve(expected_inserts);

  // Hash bucket count is data-dependent, but reserving a rough upper bound
  // helps avoid rehashing during ingestion.
  hash_index_.reserve(expected_deletes + expected_inserts);
}

grouped_candidates_builder::id_t
grouped_candidates_builder::add_delete(move_candidate del) {
  const id_t id = static_cast<id_t>(deletes_.size());
  const std::uint64_t h = del.hash;

  deletes_.push_back(std::move(del));
  auto &bucket = hash_index_[h];
  bucket.del_ids.push_back(id);
  return id;
}

grouped_candidates_builder::id_t
grouped_candidates_builder::add_insert(move_candidate ins) {
  const id_t id = static_cast<id_t>(inserts_.size());
  const std::uint64_t h = ins.hash;

  inserts_.push_back(std::move(ins));
  auto &bucket = hash_index_[h];
  bucket.ins_ids.push_back(id);
  return id;
}

grouped_candidates_builder::id_t
grouped_candidates_builder::add(move_candidate c) {
  if (c.kind == move_candidate::Kind::del)
    return add_delete(std::move(c));
  return add_insert(std::move(c));
}

grouped_candidates
grouped_candidates_builder::finalize(bool confirm_text_equality) {
  grouped_id_storage groups = build_groups_from_buckets(
      deletes_, inserts_, hash_index_, confirm_text_equality);

  return grouped_candidates(std::move(deletes_), std::move(inserts_),
                            std::move(groups));
}

} // namespace srcmove
