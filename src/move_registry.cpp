// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_registry.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include "move_registry.hpp"
#include "move_candidate.hpp"
#include <iostream>
#include <unordered_map>

namespace srcmove {

void move_registry::add_unmatched_original_delete(
    std::shared_ptr<move_candidate> del) {
  if (!del)
    return;
  deleted_by_hash.emplace(del->hash(), std::move(del));
  ++deletes_considered;
}

void move_registry::add_unmatched_modified_insert(
    std::shared_ptr<move_candidate> ins) {
  if (!ins)
    return;
  inserted_by_hash.emplace(ins->hash(), std::move(ins));
  ++inserts_registered;
}

std::unordered_map<int, std::pair<std::shared_ptr<move_candidate>,
                                  std::shared_ptr<move_candidate>>>
move_registry::get_move_pairs() {

  // For each unmatched delete, try to find an unmatched insert with the same
  // hash.
  for (auto del_it = deleted_by_hash.begin();
       del_it != deleted_by_hash.end();) {

    const std::size_t hash = del_it->first;

    // Grab any one insert with the same hash (multimap supports duplicates).
    auto ins_it = inserted_by_hash.find(hash);
    if (ins_it == inserted_by_hash.end()) {
      ++del_it;
      continue;
    }

    std::shared_ptr<move_candidate> del = del_it->second;
    std::shared_ptr<move_candidate> ins = ins_it->second;

    const int move_id = ++next_move_id;
    move_pairs.emplace(move_id, std::make_pair(std::move(del), std::move(ins)));

    ++moves_marked;

    // Remove exactly these matched entries from the unmatched pools.
    del_it = deleted_by_hash.erase(del_it);
    inserted_by_hash.erase(ins_it);
  }

  return move_pairs;
}

void move_registry::clear() {
  std::cout << *this << std::endl;
  inserted_by_hash.clear();
  deleted_by_hash.clear();
  move_pairs.clear();
  next_move_id = 0;
  inserts_registered = 0;
  deletes_considered = 0;
  moves_marked = 0;
}

void move_registry::debug() const {
  std::cout << "= Move Registry Start ==============\n"
            << "   next_move_id: " << next_move_id << "\n"
            << "   inserts_registered: " << inserts_registered << "\n"
            << "   deletes_considered: " << deletes_considered << "\n"
            << "   moves_marked: " << moves_marked << "\n"
            << "   Matched Moves:\n";

  for (const auto &[move_id, p] : move_pairs) {
    const std::shared_ptr<move_candidate> &del = p.first;
    const std::shared_ptr<move_candidate> &ins = p.second;

    std::cout << "     move " << move_id << ": "
              << (del ? del->debug_id() : "<null>") << "  ->  "
              << (ins ? ins->debug_id() : "<null>") << "\n";
  }

  std::cout << "   Deleted constructs:\n";
  for (auto &[hash, c] : deleted_by_hash) {
    std::cout << "     " << c->debug_id() << "\n";
  }

  std::cout << "   Inserted constructs:\n";
  for (auto &[hash, c] : inserted_by_hash) {
    std::cout << "     " << c->debug_id() << "\n";
  }

  std::cout << "= Move Registry End =================" << std::endl;
}

std::ostream &operator<<(std::ostream &os, const move_registry &mr) {
  mr.debug();
  return os;
}

} // namespace srcmove
