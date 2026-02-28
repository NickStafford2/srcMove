// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_registry.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
// SPDX-License-Identifier: GPL-3.0-only
#include "move_registry.hpp"

#include <iostream>
#include <utility>

namespace srcmove {

void move_registry::add_unmatched_original_delete(move_candidate del) {
  const std::size_t h = del.hash();
  deleted_by_hash_.emplace(h, std::move(del));
  ++deletes_registered_;
}

void move_registry::add_unmatched_modified_insert(move_candidate ins) {
  const std::size_t h = ins.hash();
  inserted_by_hash_.emplace(h, std::move(ins));
  ++inserts_registered_;
}

std::vector<move_registry::move_id_t> move_registry::match_all() {
  std::vector<move_id_t> created;

  // For each delete, attempt to match one insert in same hash bucket.
  for (auto del_it = deleted_by_hash_.begin();
       del_it != deleted_by_hash_.end();) {
    const std::size_t h = del_it->first;

    auto ins_it = inserted_by_hash_.find(h);
    if (ins_it == inserted_by_hash_.end()) {
      ++del_it;
      continue;
    }

    move_candidate del = std::move(del_it->second);
    move_candidate ins = std::move(ins_it->second);

    const move_id_t id = next_move_id();
    moves_.emplace(id, move_candidate_pair{std::move(del), std::move(ins)});
    created.push_back(id);
    ++moves_marked_;

    del_it = deleted_by_hash_.erase(del_it);
    inserted_by_hash_.erase(ins_it);
  }

  return created;
}

void move_registry::clear() {
  inserted_by_hash_.clear();
  deleted_by_hash_.clear();
  moves_.clear();
  next_id_ = 1;
  inserts_registered_ = 0;
  deletes_registered_ = 0;
  moves_marked_ = 0;
}

void move_registry::debug(std::ostream &os) const {
  os << "= Move Registry Start ==============\n";
  os << "next_id: " << next_id_ << "\n";
  os << "inserts_registered: " << inserts_registered_ << "\n";
  os << "deletes_registered: " << deletes_registered_ << "\n";
  os << "moves_marked: " << moves_marked_ << "\n";

  os << "Matched Moves:\n";
  for (const auto &[id, pair] : moves_) {
    os << "  move " << id << ": " << pair.debug_id() << "\n";
  }

  os << "Unmatched Deletes:\n";
  for (const auto &[h, c] : deleted_by_hash_) {
    os << "  " << h << " " << c.debug_id() << "\n";
  }

  os << "Unmatched Inserts:\n";
  for (const auto &[h, c] : inserted_by_hash_) {
    os << "  " << h << " " << c.debug_id() << "\n";
  }

  os << "= Move Registry End =================\n";
}

std::ostream &operator<<(std::ostream &os, const move_registry &mr) {
  mr.debug(os);
  return os;
}

} // namespace srcmove
