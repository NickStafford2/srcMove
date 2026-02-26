// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_candidate.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include "move_candidate.hpp"

#include <sstream>

namespace srcmove {

static std::size_t hash_combine(std::size_t seed, std::size_t v) noexcept {
  // Classic hash combine; good enough for bucketing.
  seed ^= v + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2);
  return seed;
}
bool move_candidate::operator==(const move_candidate &other) const {
  // return type == other.type && name == node.name && content == node.content;
  return full_name == other.full_name;
}

std::string move_candidate::debug_id() const {
  std::ostringstream oss;
  oss << filename << ":" << "page_position.first" << ":"
      << "page_position.second"
      << " chars=" << "number_of_characters";
  return oss.str();
}

} // namespace srcmove
