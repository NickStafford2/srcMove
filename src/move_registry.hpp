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

// #include "../model/construct.hpp"
#include <cstddef>
#include <iosfwd>
#include <memory>
#include <unordered_map>

class construct; // forward declare

namespace srcdiff {

// todo. add some way to measure distance between constructs. may need to wrap
// construct. todo. maybe check for pairs on every insert.

struct move_registry {

  // Hash -> inserted construct (duplicates allowed)
  std::unordered_multimap<std::size_t, std::shared_ptr<const construct>>
      inserted_by_hash;
  std::unordered_multimap<std::size_t, std::shared_ptr<const construct>>
      deleted_by_hash;
  std::unordered_map<int, std::pair<std::shared_ptr<const construct>,
                                    std::shared_ptr<const construct>>>
      move_pairs;

  // Monotonically increasing move id (1, 2, 3, ...)
  int next_move_id = 1;
  int get_next_move_id() { return next_move_id++; }

  // Optional debug counters
  std::size_t inserts_registered = 0;
  std::size_t deletes_considered = 0;
  std::size_t moves_marked = 0;

  void clear();
  void add_unmatched_original_delete(std::shared_ptr<const construct> del);
  void add_unmatched_modified_insert(std::shared_ptr<const construct> ins);

  std::unordered_map<int, std::pair<std::shared_ptr<const construct>,
                                    std::shared_ptr<const construct>>>
  find_move_pairs();
  void debug() const;
};

std::ostream &operator<<(std::ostream &os, const move_registry &mr);

} // namespace srcdiff
#endif
