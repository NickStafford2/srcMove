// src/move_groups.hpp
// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_groups.hpp
 *
 * Grouping model produced from hash buckets:
 * - flat id arrays (stable storage)
 * - lightweight views that reference ranges in the flat arrays
 */
#ifndef INCLUDED_MOVE_GROUPS_HPP
#define INCLUDED_MOVE_GROUPS_HPP

#include <cstdint>
#include <vector>

#include "move_buckets.hpp"

namespace srcmove {

enum class group_kind : std::uint8_t {
  move_1_to_1,    // del=1 ins=1
  moves_many,     // del=k ins=k (k>1) ambiguous pairing
  delete_only,    // del>0 ins=0
  insert_only,    // del=0 ins>0
  copy_or_repeat, // del>0 ins!=del (policy-dependent)
  ambiguous       // everything else / policy-specific
};

/**
 * A compact view over one "content group".
 *
 * A content group represents candidates that share the same primary hash and
 * (if exact confirmation is enabled) the same exact full_text.
 *
 * The group does not store ids directly; instead it stores index ranges into
 * the flat arrays in move_groups.
 */
struct content_group_compact {
  std::uint64_t content_hash = 0; // primary bucket key (fast_hash_raw)
  std::uint32_t group_id = 0;     // stable id within a build result

  // ranges into internal vectors of ids (not iterators to avoid invalidation)
  std::uint32_t del_begin = 0, del_end = 0; // [begin, end)
  std::uint32_t ins_begin = 0, ins_end = 0; // [begin, end)

  group_kind kind = group_kind::ambiguous;

  std::size_t del_count() const {
    return static_cast<std::size_t>(del_end - del_begin);
  }
  std::size_t ins_count() const {
    return static_cast<std::size_t>(ins_end - ins_begin);
  }
};

/**
 * Result of building groups from hash buckets.
 *
 * groups[i] references ranges inside group_del_ids / group_ins_ids.
 */
struct content_group_storage {
  std::vector<candidate_id> group_del_ids;
  std::vector<candidate_id> group_ins_ids;
  std::vector<content_group_compact> groups;

  void clear() {
    group_del_ids.clear();
    group_ins_ids.clear();
    groups.clear();
  }
};

} // namespace srcmove

#endif
