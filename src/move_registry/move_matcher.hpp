// SPDX-License-Identifier: GPL-3.0-only
#ifndef INCLUDED_MOVE_MATCHER_HPP
#define INCLUDED_MOVE_MATCHER_HPP

#include <cstddef>
#include <vector>

#include "grouped_candidates.hpp"

namespace srcmove {

// FAST baseline: 1-to-1 consumption inside each content group
std::vector<move_match> greedy_match_1_to_1(const grouped_candidates &mr);

// Potentially large: D×I per group (use hard_cap to stop early)
std::vector<move_match> enumerate_all_pairs(const grouped_candidates &mr,
                                            std::size_t hard_cap = SIZE_MAX);

} // namespace srcmove
#endif
