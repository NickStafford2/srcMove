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
#include <cstddef>
#include <iosfwd>
#include <memory>
#include <unordered_map>

namespace srcmove {

// todo. add some way to measure distance between constructs. may need to wrap
// construct. todo. maybe check for pairs on every insert.

class move_registry {
private:
  std::unordered_multimap<std::size_t, std::shared_ptr<move_candidate>>
      inserted_by_hash;
  std::unordered_multimap<std::size_t, std::shared_ptr<move_candidate>>
      deleted_by_hash;
  std::unordered_map<int, std::pair<std::shared_ptr<move_candidate>,
                                    std::shared_ptr<move_candidate>>>
      move_pairs;

  // Monotonically increasing move id (1, 2, 3, ...)
  int next_move_id = 1;

  // Optional debug counters
  std::size_t inserts_registered = 0;
  std::size_t deletes_considered = 0;
  std::size_t moves_marked = 0;

public:
  // Hash -> inserted construct (duplicates allowed)
  int get_next_move_id() { return next_move_id++; }

  void clear();
  void add_unmatched_original_delete(std::shared_ptr<move_candidate> del);
  void add_unmatched_modified_insert(std::shared_ptr<move_candidate> ins);

  std::unordered_map<int, std::pair<std::shared_ptr<move_candidate>,
                                    std::shared_ptr<move_candidate>>>
  get_move_pairs();
  void debug() const;
};

std::ostream &operator<<(std::ostream &os, const move_registry &mr);

} // namespace srcmove
#endif
