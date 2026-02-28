// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file clone_detection.hpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */

#include "move_candidate.hpp"

namespace srcmove {

bool is_clone(move_candidate original, move_candidate modified);

bool is_clone_type_1(move_candidate original, move_candidate modified) {
  // normalize source text. (remove comments/whitespace)
  // split into lines or blocks
  // hash or compare strings

  // ideas
  // line by line hashing
  // sliding window hashing
  // suffix trees / suffix arrays
  return true;
}
bool is_clone_type_2(move_candidate original, move_candidate modified) {
  // tokanize parameters
  return is_clone_type_1(original, modified);
}
bool is_clone_type_3(move_candidate original, move_candidate modified);
bool is_clone_type_4(move_candidate original, move_candidate modified);

} // namespace srcmove
