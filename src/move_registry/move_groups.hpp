// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_groups.hpp
 *
 * Grouping model produced from hash buckets:
 * - flat id arrays (stable storage)
 * - lightweight views that reference ranges in the flat arrays
 */
// SPDX-License-Identifier: GPL-3.0-only
#ifndef INCLUDED_MOVE_GROUPS_HPP
#define INCLUDED_MOVE_GROUPS_HPP

#include <cstddef>
#include <cstdint>
#include <vector>

#include "move_buckets.hpp"
#include "move_registry/candidate_registry.hpp"

namespace srcmove {

class candidate_registry;

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
  std::uint32_t group_id = 0;

  std::uint32_t del_begin = 0;
  std::uint32_t del_end = 0;
  std::uint32_t ins_begin = 0;
  std::uint32_t ins_end = 0;

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
  using id_t = candidate_id;

  struct id_view {
    const id_t *data = nullptr;
    std::size_t count = 0;

    const id_t *begin() const noexcept { return data; }
    const id_t *end() const noexcept { return data + count; }
    std::size_t size() const noexcept { return count; }

    const id_t &operator[](std::size_t i) const noexcept { return data[i]; }
  };

  void clear();

  const std::vector<content_group> &groups() const noexcept { return groups_; }

  id_view delete_ids(const content_group &g) const noexcept;
  id_view insert_ids(const content_group &g) const noexcept;

  std::size_t group_count() const noexcept { return groups_.size(); }

  std::uint32_t append_delete_ids(const std::vector<id_t> &ids) {
    const std::uint32_t begin =
        static_cast<std::uint32_t>(group_del_ids_.size());
    group_del_ids_.insert(group_del_ids_.end(), ids.begin(), ids.end());
    return begin;
  }

  std::uint32_t append_insert_ids(const std::vector<id_t> &ids) {
    const std::uint32_t begin =
        static_cast<std::uint32_t>(group_ins_ids_.size());
    group_ins_ids_.insert(group_ins_ids_.end(), ids.begin(), ids.end());
    return begin;
  }

  void append_group(content_group g) { groups_.push_back(g); }

private:
  friend content_groups build_content_groups(const candidate_registry &registry,
                                             bool confirm_text_equality);

  std::vector<id_t> group_del_ids_;
  std::vector<id_t> group_ins_ids_;
  std::vector<content_group> groups_;
};

} // namespace srcmove

#endif
