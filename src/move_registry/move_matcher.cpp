// SPDX-License-Identifier: GPL-3.0-only
#include "move_matcher.hpp"

#include <algorithm>
#include <cstddef>
#include <vector>

namespace srcmove {

std::vector<move_match> greedy_match_1_to_1(const content_groups &groups) {
  std::vector<move_match> out;

  std::size_t cap = 0;
  for (const auto &g : groups.groups()) {
    cap += std::min(g.del_count(), g.ins_count());
  }
  out.reserve(cap);

  for (const auto &g : groups.groups()) {
    const auto del_ids = groups.delete_ids(g);
    const auto ins_ids = groups.insert_ids(g);

    const std::size_t n = std::min(del_ids.size(), ins_ids.size());
    for (std::size_t i = 0; i < n; ++i) {
      out.push_back(move_match{del_ids[i], ins_ids[i]});
    }
  }

  return out;
}

std::vector<move_match> enumerate_all_pairs(const content_groups &groups,
                                            std::size_t hard_cap) {
  std::vector<move_match> out;

  for (const auto &g : groups.groups()) {
    const auto del_ids = groups.delete_ids(g);
    const auto ins_ids = groups.insert_ids(g);

    const std::size_t d = del_ids.size();
    const std::size_t i = ins_ids.size();

    if (d == 0 || i == 0) {
      continue;
    }

    if (hard_cap != SIZE_MAX) {
      const unsigned __int128 needed =
          static_cast<unsigned __int128>(d) * static_cast<unsigned __int128>(i);
      const unsigned __int128 remaining =
          (hard_cap > out.size()) ? (hard_cap - out.size()) : 0;

      if (needed > remaining) {
        break;
      }
    }

    for (std::size_t di = 0; di < d; ++di) {
      for (std::size_t ii = 0; ii < i; ++ii) {
        out.push_back(move_match{del_ids[di], ins_ids[ii]});
      }
    }
  }

  return out;
}

} // namespace srcmove
