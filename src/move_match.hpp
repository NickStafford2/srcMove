// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_match.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */

#include "move_candidate.hpp"
#include <vector>

namespace srcmove {

struct move_match {
  const move_candidate *del;
  const move_candidate *ins;
};

std::vector<move_match>
find_matching_regions_by_hash(const std::vector<move_candidate> &regions,
                              bool confirm_text_equality);
}; // namespace srcmove
