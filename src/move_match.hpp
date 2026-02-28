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

// For each delete region, this function finds all insert regions with the
// same content hash (and optionally identical full text).
//
// It builds a hash index of inserts, then for each delete performs a fast
// lookup to retrieve all inserts sharing that hash. For every matching
// (delete, insert) pair, a move_match is emitted.
//
// Important: this generates a many-to-many set of candidate matches.
// If there are 3 deletes and 2 inserts with identical content,
// this will produce 3 × 2 = 6 matches (cartesian product).
//
// No 1-to-1 pairing or conflict resolution is done here — this function
// only generates candidate move pairs.
std::vector<move_match>
find_matching_regions(const std::vector<move_candidate> &regions);

std::ostream &operator<<(std::ostream &os, const move_match &m);

}; // namespace srcmove
