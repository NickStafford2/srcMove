// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_registry.hpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */

#ifndef INCLUDED_MOVE_REGISTRY_HPP
#define INCLUDED_MOVE_REGISTRY_HPP

#include "move_candidate.hpp"
#include "move_candidate_pair.hpp"

#include <cstddef>
#include <cstdint>
#include <iosfwd>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace srcmove {

// Store candidates by value; registry owns them.
// Pairing is done by bucket key (content_hash()).
// match_all() consumes one insert for one delete per bucket (simple
//  baseline).
class move_registry {
public:
  using move_id_t = std::int32_t;

  void clear();

  void add_unmatched_original_delete(move_candidate del);
  void add_unmatched_modified_insert(move_candidate ins);

  // Matches and returns new move pairs; also stores them internally.
  std::vector<move_id_t> match_all();

  const std::unordered_map<move_id_t, move_candidate_pair> &
  moves() const noexcept {
    return moves_;
  }

  // Debug/metrics
  void debug(std::ostream &os) const;

private:
  move_id_t next_id_ = 1;

  // hash -> candidates (duplicates allowed)
  std::unordered_multimap<std::size_t, move_candidate> inserted_by_hash_;
  std::unordered_multimap<std::size_t, move_candidate> deleted_by_hash_;

  std::unordered_map<move_id_t, move_candidate_pair> moves_;

  std::size_t inserts_registered_ = 0;
  std::size_t deletes_registered_ = 0;
  std::size_t moves_marked_ = 0;

  move_id_t next_move_id() noexcept { return next_id_++; }
};

std::ostream &operator<<(std::ostream &os, const move_registry &mr);

} // namespace srcmove

#endif
