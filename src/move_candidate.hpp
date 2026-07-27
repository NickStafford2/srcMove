// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_candidate.hpp
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
  enum class Role {
    diff_wrapper,
    single_child_wrapper,
    multi_child_wrapper,
    structural_child,
  };

  move_candidate(Kind        kind,
                 std::size_t start_idx,
                 std::string filename,
                 std::string raw_text,
                 std::string canonical_text,
                 std::string type2_canonical_text,
                 bool        type2_eligible = false);

  Kind        kind;
  std::string filename; // from unit@filename
  std::string xpath;
  std::string full_name;
  std::size_t sibling_index; // 1-based for siblings with same name under parent
  std::size_t start_index;
  std::size_t start_idx;
  std::size_t end_idx;
  std::string raw_text;             // exact region inner text, for debug
  std::string canonical_text;       // normalized subtree identity, for matching
  std::string type2_canonical_text; // identifier-normalized subtree identity
  bool type2_eligible; // true for statement-level-or-larger type 2 matching
  Role role = Role::diff_wrapper;
  std::uint64_t hash;
  std::uint64_t type2_hash;

  std::size_t add_child_and_get_next_id(std::string full_name) {
    return ++child_counts[full_name];
  }
  // std::size_t move_candidate::hash() const noexcept
  bool operator==(const move_candidate &other) const;

  std::string          debug_id() const;
  static std::uint64_t fast_hash_raw(std::string_view s);

private:
  std::unordered_map<std::string, std::size_t> child_counts;
};

std::ostream &operator<<(std::ostream &os, const move_candidate &r);
} // namespace srcmove

#endif
