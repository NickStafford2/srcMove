// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_candidate.hpp
 */
#ifndef INCLUDED_MOVE_CANDIDATE_HPP
#define INCLUDED_MOVE_CANDIDATE_HPP

#include <boost/optional.hpp> // May not be needed anymore. Try removing after thesis is finished. 
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <memory>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "location_context.hpp"

namespace srcmove {

enum srcml_node_type : unsigned int { OTHER = 0, START = 1, END = 2, TEXT = 3 };

// srcML represents built-in type keywords as names too. They do not provide
// evidence for a program-identifier replacement.
inline bool builtin_type_name(std::string_view name) {
  bool found = false;
  std::size_t start = 0;
  while (start < name.size()) {
    const auto first = name.find_first_not_of(" \t\n\r", start);
    if (first == std::string_view::npos) break;
    const auto end = name.find_first_of(" \t\n\r", first);
    const auto word = name.substr(first, end == std::string_view::npos ? end : end - first);
    if (!(word == "void" || word == "bool" || word == "char" ||
          word == "short" || word == "int" || word == "long" ||
          word == "float" || word == "double" || word == "signed" ||
          word == "unsigned" || word == "auto" || word == "wchar_t" ||
          word == "char8_t" || word == "char16_t" || word == "char32_t")) return false;
    found = true;
    if (end == std::string_view::npos) break;
    start = end + 1;
  }
  return found;
}

// Independent continuing-source evidence; empty values denote inconsistent maps.
struct continuing_name_evidence {
  std::unordered_map<std::string, std::string> forward;
  std::unordered_map<std::string, std::string> reverse;
};

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
                 std::vector<std::uint64_t> type2_normalized_lines,
                 std::vector<std::uint64_t> type3_normalized_tokens,
                 bool        type2_eligible = false);

  Kind        kind;
  std::string filename; // from unit@filename
  std::string xpath;
  std::string full_name;
  std::size_t sibling_index; // 1-based for siblings with same name under parent
  std::size_t start_index;
  std::size_t start_idx;
  std::size_t end_idx;
  // The enclosing srcDiff region and its revision-independent structural
  // parent. Selection uses this context to distinguish an adjacent in-place
  // replacement from a relocation.
  std::size_t diff_region_start_idx;
  std::size_t diff_region_end_idx;
  std::string structural_parent_key;
  std::size_t structural_parent_depth = 0;
  // Revision-projected direct source siblings, independent of candidate
  // filtering. Diff wrappers, comments, and whitespace are transparent;
  // preprocessor children consume ordinals as sequence barriers.
  std::string sequence_parent_id;
  std::size_t sequence_sibling_ordinal = 0;
  bool sequence_context_reliable = false;
  endpoint_location_context location;
  std::string raw_text;             // exact region inner text, for debug
  std::string canonical_text;       // normalized subtree identity, for matching
  std::string type2b_canonical_text; // populated only for CLI diagnostics
  std::string type2_canonical_text; // compact, consistently normalized identity
  std::vector<std::uint64_t> type2_normalized_lines; // cached Type-3 sequence
  std::vector<std::uint64_t> type3_normalized_tokens; // consistent name tokens
  std::vector<std::pair<std::string, std::string>> member_accesses;
  std::vector<std::string> identifier_names;
  std::vector<std::string> identifier_qualifiers;
  std::string identity_scope; // mapped lexical block, never inferred from moves
  std::shared_ptr<const continuing_name_evidence> continuing_names;
  std::shared_ptr<const continuing_name_evidence> continuing_fields;
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
