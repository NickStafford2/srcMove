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
find_matching_regions(const std::vector<move_candidate> &regions,
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

std::ostream &operator<<(std::ostream &os, const move_match &m) {
  std::string tab = "       ";

  return os << tab << "DEL [" << m.del->start_idx << "," << m.del->end_idx
            << "] " << m.del->filename << "\n"
            << tab << "INS [" << m.ins->start_idx << "," << m.ins->end_idx
            << "] " << m.ins->filename << "\n"
            << tab << "hash=" << m.del->hash << "\n"
            << tab << "text: '" << m.del->full_text << "'";
}

/*
=== HASH MATCHES (DEL -> INS) ===
DEL [19,59] test/simple/original.cpp|test/simple/modified.cpp  ->  INS [87,127]
test/simple/original.cpp|test/simple/modified.cpp  hash=5785509076557761878
chars(del)=19  chars(ins)=19 raw.ins: '  int first = 123;
'
  raw.del: '  int first = 123;
'

DEL [24,55] test/simple/original.cpp|test/simple/modified.cpp  ->  INS [92,123]
test/simple/original.cpp|test/simple/modified.cpp  hash=8452670157112265760
chars(del)=16  chars(ins)=16 raw.ins: 'int first = 123;' raw.del: 'int first =
123;'
*
*/
}; // namespace srcmove
