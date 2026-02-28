// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_candidate_pair.hpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#ifndef INCLUDED_MOVE_CANDIDATE_PAIR_HPP
#define INCLUDED_MOVE_CANDIDATE_PAIR_HPP

#include "move_candidate.hpp"

#include <cstddef>
#include <string>

namespace srcmove {

struct move_candidate_pair {
  move_candidate original; // delete
  move_candidate modified; // insert

  // 0.0..1.0 heuristic. This should eventually live in a separate scorer
  // component.
  float likelihood() const noexcept;

  std::size_t hash() const noexcept;
  std::string debug_id() const;
};

} // namespace srcmove
#endif
