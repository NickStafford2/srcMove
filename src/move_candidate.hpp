// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_candidate.hpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#ifndef INCLUDED_MOVE_CANDIDATE_HPP
#define INCLUDED_MOVE_CANDIDATE_HPP

#include <cstddef>
#include <iostream>
#include <string>
#include <unordered_map>

namespace srcmove {

class move_candidate {
public:
  std::string filename; // from unit@filename
  std::string xpath;
  std::string full_name;     // full_name()
  std::size_t sibling_index; // 1-based for siblings with same name under parent
  std::size_t start_index;

  std::size_t add_child_and_get_next_id(std::string full_name) {
    return ++child_counts[full_name];
  }

private:
  std::unordered_map<std::string, std::size_t> child_counts;
};

std::ostream &operator<<(std::ostream &os, const move_candidate &r) {
  return os << "xpath=" << r.xpath;
}

/*
locality of behavior
Use several factors to measure the confidence that something is a move.
  assign points to each one.
  can change values depending on user experience feedback.
size of the move
  small lines of code are more likely to be rewritten.
  giant functions moved across files are almost certainly moves
distance to move in the directory tree.
distance to move on page. rows/columns  --position
distance to move between blocks.
Similarity of the two code segments.

can be either original or modified.

either an insert or delete operation in a source diff

// This should be the output of the parser.
struct move_candidate {
  // Relative to project root (or whatever your parser chooses as root).
  std::string file_path;

  // Raw representation (useful for debugging, not a great matching key
  // long-term).
  std::string as_string;

  // Context string (parent blocks, surrounding scope, etc.).
  // When parser is introduced, consider storing a structured representation
  // instead.
  std::string context;

  // Size in characters of the moved/deleted/inserted region.
  std::size_t number_of_characters = 0;

  // Row/column of first character (1-based or 0-based: pick one and document
  // it).
  std::pair<std::size_t, std::size_t> page_position{0, 0};

  // Content fingerprint used for initial bucketing.
  // Today: hash(as_string). Tomorrow: hash(AST subtree signature) or token
  // stream signature.
  std::size_t hash() const noexcept;

  // Debug-friendly id.
  std::string debug_id() const;
};
*/

} // namespace srcmove
#endif
