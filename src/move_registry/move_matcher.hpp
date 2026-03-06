// SPDX-License-Identifier: GPL-3.0-only
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

// FAST baseline: 1-to-1 consumption inside each content group
std::vector<move_match> greedy_match_1_to_1(const content_groups &groups);

// Potentially large: D×I per group (use hard_cap to stop early)
std::vector<move_match> enumerate_all_pairs(const content_groups &groups,
                                            std::size_t hard_cap = SIZE_MAX);

} // namespace srcmove
#endif
