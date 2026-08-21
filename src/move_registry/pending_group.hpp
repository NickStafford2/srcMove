// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file pending_group.hpp
 *
 * Internal grouped-candidate work item used while building content groups.
 */
#ifndef INCLUDED_MOVE_PENDING_GROUP_HPP
#define INCLUDED_MOVE_PENDING_GROUP_HPP

#include <cstdint>
#include <vector>

#include "move_registry/content_groups.hpp"
#include "move_registry/move_buckets.hpp"

namespace srcmove {

struct pending_group {
  std::uint64_t             content_hash = 0;
  match_kind                match        = match_kind::unmatched;
  std::vector<candidate_id> del_ids;
  std::vector<candidate_id> ins_ids;
};

bool has_both_sides(const pending_group &group);
bool is_one_to_one(const pending_group &group);

} // namespace srcmove

#endif
