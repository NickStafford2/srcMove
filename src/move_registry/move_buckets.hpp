// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_registry/move_buckets.hpp
 *
 * Build-time hash buckets used by move_registry grouping.
 */
#ifndef INCLUDED_MOVE_BUCKETS_HPP
#define INCLUDED_MOVE_BUCKETS_HPP

#include <cstdint>
#include <vector>

namespace srcmove {

using candidate_id = std::uint32_t;

struct bucket_ids {
  std::vector<candidate_id> del_ids;
  std::vector<candidate_id> ins_ids;

  bool empty() const noexcept { return del_ids.empty() && ins_ids.empty(); }

  void clear() {
    del_ids.clear();
    ins_ids.clear();
  }
};

} // namespace srcmove

#endif
