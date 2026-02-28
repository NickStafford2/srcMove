// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file pipeline.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include <cstdint>
#include <unordered_map>
#include <vector>

#include "move_match.hpp"

namespace srcmove {

std::vector<move_match>
find_matching_regions_by_hash(const std::vector<move_candidate> &regions,
                              bool confirm_text_equality) {
  std::unordered_multimap<std::uint64_t, const move_candidate *>
      inserts_by_hash;
  inserts_by_hash.reserve(regions.size());

  std::vector<const move_candidate *> deletes;
  deletes.reserve(regions.size());

  for (const auto &r : regions) {
    if (r.kind == move_candidate::Kind::insert) {
      inserts_by_hash.emplace(r.hash, &r);
    } else {
      deletes.push_back(&r);
    }
  }

  std::vector<move_match> matches;
  matches.reserve(std::min(deletes.size(), inserts_by_hash.size()));

  for (const move_candidate *d : deletes) {
    auto [it, end] = inserts_by_hash.equal_range(d->hash);
    for (; it != end; ++it) {
      const move_candidate *ins = it->second;

      if (confirm_text_equality && d->full_text != ins->full_text)
        continue;

      matches.push_back(move_match{d, ins});
    }
  }
  return matches;
}
}; // namespace srcmove
