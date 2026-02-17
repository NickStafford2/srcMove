// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_candidate_pair.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */

#include "move_candidate_pair.hpp"

#include <algorithm>
#include <functional>
#include <sstream>

namespace srcmove {

static std::size_t hash_combine(std::size_t seed, std::size_t v) noexcept {
  seed ^= v + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2);
  return seed;
}

float move_candidate_pair::likelihood() const noexcept {
  // This is intentionally a placeholder heuristic.
  // Once I add the parser, I will add features like:
  // - normalized token similarity / subtree similarity
  // - context similarity (enclosing scope signature)
  // - path distance / directory distance
  // - size weighting (bigger moves more likely real moves)
  // Keep this deterministic and unit-test it.
  float score = 0.0f;

  if (original.hash() == modified.hash()) {
    score += 0.6f;
  }

  const auto size_min =
      std::min(original.number_of_characters, modified.number_of_characters);
  const auto size_max =
      std::max(original.number_of_characters, modified.number_of_characters);
  if (size_max > 0) {
    const float size_ratio =
        static_cast<float>(size_min) / static_cast<float>(size_max);
    score += 0.4f * size_ratio;
  }

  if (score > 1.0f)
    score = 1.0f;
  return score;
}

std::size_t move_candidate_pair::hash() const noexcept {
  std::size_t h = 0;
  h = hash_combine(h, original.hash());
  h = hash_combine(h, modified.hash());
  return h;
}

std::string move_candidate_pair::debug_id() const {
  std::ostringstream oss;
  oss << original.debug_id() << " -> " << modified.debug_id()
      << " likelihood=" << likelihood();
  return oss.str();
}

} // namespace srcmove
