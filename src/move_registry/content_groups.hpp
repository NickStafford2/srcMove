// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file content_groups.hpp
 *
 * Compact representation of "content groups".
 *
 * A content group represents candidates that share the same hash
 * (and optionally identical full text).
 *
 * Design goals:
 * - avoid storing candidate objects repeatedly
 * - keep contiguous arrays of candidate ids for cache locality
 * - allow efficient iteration over delete/insert sides of each group
 *
 * Layout:
 *   group_del_ids_   flat array of delete candidate ids
 *   group_ins_ids_   flat array of insert candidate ids
 *   groups_          metadata describing ranges inside those arrays
 *
 * Each group stores index ranges into the flat arrays instead of
 * owning its own vectors. This keeps memory compact and iteration fast.
 */

#ifndef INCLUDED_MOVE_CONTENT_GROUPS_HPP
#define INCLUDED_MOVE_CONTENT_GROUPS_HPP

#include <cstddef>
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

struct content_group {
  std::uint64_t content_hash = 0;
  std::uint32_t group_id     = 0;

  // Ranges inside group_del_ids_ and group_ins_ids_
  std::uint32_t del_begin = 0;
  std::uint32_t del_end   = 0;
  std::uint32_t ins_begin = 0;
  std::uint32_t ins_end   = 0;

  group_kind kind = group_kind::ambiguous;

  std::size_t del_count() const noexcept {
    return static_cast<std::size_t>(del_end - del_begin);
  }

  std::size_t ins_count() const noexcept {
    return static_cast<std::size_t>(ins_end - ins_begin);
  }
};

class content_groups {
public:
  using id_t = candidate_id; // todo: remove this

  /**
   * Lightweight non-owning view over a contiguous id range.
   * Used to iterate group delete/insert ids without copying.
   */
  struct id_view {
    const id_t *data  = nullptr;
    std::size_t count = 0;

    const id_t *begin() const noexcept { return data; }
    const id_t *end() const noexcept { return data + count; }
    std::size_t size() const noexcept { return count; }

    const id_t &operator[](std::size_t i) const noexcept { return data[i]; }
  };

  void clear();

  const std::vector<content_group> &groups() const noexcept { return groups_; }

  // Access delete ids belonging to a group.
  id_view delete_ids(const content_group &g) const noexcept;

  // Access insert ids belonging to a group.
  id_view insert_ids(const content_group &g) const noexcept;

  std::size_t group_count() const noexcept { return groups_.size(); }

  // ----- Builder-facing helpers -----

  void reserve_groups(std::size_t n) { groups_.reserve(n); }

  // Append ids and return the starting index of the inserted range.
  std::uint32_t append_delete_ids(const std::vector<id_t> &ids);

  std::uint32_t append_insert_ids(const std::vector<id_t> &ids);

  void append_group(content_group g);

private:
  std::vector<id_t>          group_del_ids_;
  std::vector<id_t>          group_ins_ids_;
  std::vector<content_group> groups_;
};

} // namespace srcmove

#endif
