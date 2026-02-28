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

#include <boost/optional.hpp>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <string>
#include <string_view>
#include <unordered_map>

namespace srcmove {

enum srcml_node_type : unsigned int { OTHER = 0, START = 1, END = 2, TEXT = 3 };

class move_candidate {
public:
  enum class Kind { insert, del };

  move_candidate(Kind kind, std::size_t start_idx, std::string filename,
                 std::string full_text);
  Kind kind;
  std::string filename; // from unit@filename
  std::string xpath;
  std::string full_name;     // full_name()
  std::size_t sibling_index; // 1-based for siblings with same name under parent
  std::size_t start_index;
  std::size_t start_idx;
  std::size_t end_idx;
  std::string full_text;
  std::uint64_t hash;

  std::size_t add_child_and_get_next_id(std::string full_name) {
    return ++child_counts[full_name];
  }
  // std::size_t move_candidate::hash() const noexcept
  bool operator==(const move_candidate &other) const;

  std::string debug_id() const;
  static std::uint64_t fast_hash_raw(std::string_view s);

private:
  std::unordered_map<std::string, std::size_t> child_counts;
};

std::ostream &operator<<(std::ostream &os, const move_candidate &r);

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
*/
} // namespace srcmove

#endif
