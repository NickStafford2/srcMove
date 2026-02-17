// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_candidate.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include "move_candidate.hpp"

#include <functional>
#include <sstream>

namespace srcmove {

static std::size_t hash_combine(std::size_t seed, std::size_t v) noexcept {
  // Classic hash combine; good enough for bucketing.
  seed ^= v + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2);
  return seed;
}

std::size_t move_candidate::hash() const noexcept {
  // Major design note:
  // This is intentionally a "cheap bucket key" not a definitive identity.
  // Once the parser is in, replace as_string hashing with a normalized
  // signature.
  std::size_t h = 0;
  const std::hash<std::string> hs;
  h = hash_combine(h, hs(as_string));
  h = hash_combine(h, hs(context));
  h = hash_combine(h, hs(file_path));
  h = hash_combine(h, std::hash<std::size_t>{}(number_of_characters));
  return h;
}

std::string move_candidate::debug_id() const {
  std::ostringstream oss;
  oss << file_path << ":" << page_position.first << ":" << page_position.second
      << " chars=" << number_of_characters;
  return oss.str();
}

} // namespace srcmove
