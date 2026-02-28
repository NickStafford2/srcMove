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
find_matching_regions(const std::vector<move_candidate> &regions) {

  // create data structure
  // It’s a multimap because:
  //   - multiple inserts might have the same hash
  //   - so one hash key can map to multiple insert regions
  std::unordered_multimap<std::uint64_t, const move_candidate *> inserts;
  inserts.reserve(regions.size());

  std::vector<const move_candidate *> deletes;
  deletes.reserve(regions.size());

  // Partition regions into inserts and deletes
  for (const auto &r : regions) {
    if (r.kind == move_candidate::Kind::insert) {
      inserts.emplace(r.hash, &r);
    } else {
      deletes.push_back(&r);
    }
  }

  // Prepare result vector
  std::vector<move_match> matches;
  matches.reserve(std::min(deletes.size(), inserts.size()));

  // For each delete, find candidate inserts
  for (const move_candidate *d : deletes) {
    // it points to the first insert with matching hash
    // end marks the stopping point
    auto [it, end] = inserts.equal_range(d->hash);

    // Check each candidate insert
    for (; it != end; ++it) {
      const move_candidate *ins = it->second;

      assert(d->full_text == ins->full_text && "HASH COLLISION!!!!");

      matches.push_back(move_match{d, ins});
    }
  }
  return matches;
}

std::ostream &operator<<(std::ostream &os, const move_match &m) {
  std::string tab = "       ";

  return os << tab << "DEL [" << m.del->start_idx << "," << m.del->end_idx
            << "] " << m.del->filename << "\n"
            << tab << "INS [" << m.ins->start_idx << "," << m.ins->end_idx
            << "] " << m.ins->filename << "\n"
            << tab << "hash=" << m.del->hash << "\n"
            << tab << "text: '" << m.del->full_text << "'";
}

}; // namespace srcmove
