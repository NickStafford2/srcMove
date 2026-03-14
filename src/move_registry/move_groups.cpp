// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_groups.cpp
 */

#include "move_groups.hpp"

namespace srcmove {

void content_groups::clear() {
  group_del_ids_.clear();
  group_ins_ids_.clear();
  groups_.clear();
}

content_groups::id_view
content_groups::delete_ids(const content_group &g) const noexcept {
  const std::uint32_t n = g.del_end - g.del_begin;
  if (n == 0) {
    return id_view{nullptr, 0};
  }

  return id_view{&group_del_ids_[g.del_begin], static_cast<std::size_t>(n)};
}

content_groups::id_view
content_groups::insert_ids(const content_group &g) const noexcept {
  const std::uint32_t n = g.ins_end - g.ins_begin;
  if (n == 0) {
    return id_view{nullptr, 0};
  }

  return id_view{&group_ins_ids_[g.ins_begin], static_cast<std::size_t>(n)};
}

std::uint32_t content_groups::append_delete_ids(const std::vector<id_t> &ids) {
  const std::uint32_t begin = static_cast<std::uint32_t>(group_del_ids_.size());
  group_del_ids_.insert(group_del_ids_.end(), ids.begin(), ids.end());
  return begin;
}

std::uint32_t content_groups::append_insert_ids(const std::vector<id_t> &ids) {
  const std::uint32_t begin = static_cast<std::uint32_t>(group_ins_ids_.size());
  group_ins_ids_.insert(group_ins_ids_.end(), ids.begin(), ids.end());
  return begin;
}

void content_groups::append_group(content_group g) { groups_.push_back(g); }

} // namespace srcmove
