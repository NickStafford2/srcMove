// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_candidate.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */

#include <cstddef>
#include <sstream>
#include <string_view>
#include <utility>

#include "move_candidate.hpp"

namespace srcmove {

static std::size_t hash_combine(std::size_t seed, std::size_t v) noexcept {
  // Classic hash combine; good enough for bucketing.
  seed ^= v + 0x9e3779b97f4a7c15ULL + (seed << 6) + (seed >> 2);
  return seed;
}

move_candidate::move_candidate(Kind        k,
                               std::size_t start,
                               std::string file,
                               std::string raw,
                               std::string canonical)
    : kind(k), filename(std::move(file)), xpath(), full_name(),
      sibling_index(0), start_index(0), start_idx(start), end_idx(0),
      raw_text(std::move(raw)), canonical_text(std::move(canonical)),
      hash(move_candidate::fast_hash_raw(canonical_text)) {}

bool move_candidate::operator==(const move_candidate &other) const {
  // return type == other.type && name == node.name && content == node.content;
  return full_name == other.full_name;
}

std::string move_candidate::debug_id() const {
  std::ostringstream oss;
  oss << filename << ":" << "page_position.first" << ":"
      << "page_position.second" << " chars=" << "number_of_characters";
  return oss.str();
}

// 64-bit FNV-1a
std::uint64_t move_candidate::fast_hash_raw(std::string_view s) {
  std::uint64_t hash = 14695981039346656037ull; // offset basis

  for (unsigned char c : s) {
    hash ^= static_cast<std::uint64_t>(c);
    hash *= 1099511628211ull; // FNV prime
  }

  return hash;
}

std::ostream &operator<<(std::ostream &os, const move_candidate &r) {
  return os << (r.kind == move_candidate::Kind::insert ? "INS" : "DEL") << " ["
            << r.start_idx << "," << r.end_idx << "] " << r.filename
            << " hash=" << r.hash << "  raw.ins: '" << r.raw_text << "'\n";
}

} // namespace srcmove
