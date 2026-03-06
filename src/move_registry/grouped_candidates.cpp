// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file grouped_candidates.cpp
 */

#include <cassert>
#include <utility>

#include "grouped_candidates.hpp"
#include "grouped_candidates_builder.hpp"
#include "move_registry/move_groups.hpp"

namespace srcmove {

grouped_candidates::grouped_candidates(std::vector<move_candidate> deletes,
                                       std::vector<move_candidate> inserts,
                                       grouped_id_storage groups)
    : deletes_(std::move(deletes)), inserts_(std::move(inserts)),
      groups_(std::move(groups)) {}

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
  grouped_candidates_builder builder;
  builder.reserve(candidates.size(), candidates.size());

  for (auto &c : candidates) {
    builder.add(std::move(c));
  }

  return builder.finalize(confirm_text_equality);
}

} // namespace srcmove
