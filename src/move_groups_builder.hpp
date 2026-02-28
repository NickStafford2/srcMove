// src/move_groups_builder.hpp
// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_groups_builder.hpp
 *
 * Pure grouping logic extracted from move_registry.
 */
#ifndef INCLUDED_MOVE_GROUPS_BUILDER_HPP
#define INCLUDED_MOVE_GROUPS_BUILDER_HPP

#include <cstdint>
#include <unordered_map>
#include <vector>

#include "move_buckets.hpp"
#include "move_candidate.hpp"
#include "move_groups.hpp"

namespace srcmove {

/**
 * Build content groups from hash buckets.
 *
 * If confirm_text_equality is false:
 *   - one group per hash bucket
 *
 * If confirm_text_equality is true:
 *   - each hash bucket is split into subgroups by exact full_text
 *     (prevents false matches from hash collisions)
 */
move_groups build_groups_from_buckets(
    const std::vector<move_candidate> &deletes,
    const std::vector<move_candidate> &inserts,
    const std::unordered_map<std::uint64_t, bucket_ids> &by_hash,
    bool confirm_text_equality);

} // namespace srcmove

#endif
