// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_matcher.hpp
 *
 * Matching strategies applied to grouped candidates.
 *
 * Matchers operate purely on content_groups and do not mutate the registry.
 *
 * A match represents a candidate delete paired with a candidate insert.
 */

#ifndef INCLUDED_MOVE_MATCHER_HPP
#define INCLUDED_MOVE_MATCHER_HPP

#include <cstddef>
#include <vector>

#include "move_groups.hpp"

namespace srcmove {

struct move_match {
  candidate_id del_id;
  candidate_id ins_id;
};

/**
 * Greedy baseline matcher.
 *
 * For each group:
 *   pair deletes and inserts in order until one side runs out.
 *
 * Fast and deterministic, but not necessarily optimal.
 */
std::vector<move_match> greedy_match_1_to_1(const content_groups &groups);

/**
 * Enumerate every possible delete/insert pairing within groups.
 *
 * Potentially O(D×I) per group, so a hard_cap can stop expansion early.
 */
std::vector<move_match> enumerate_all_pairs(const content_groups &groups,
                                            std::size_t hard_cap = SIZE_MAX);

} // namespace srcmove

#endif
