// SPDX-License-Identifier: GPL-3.0-only
#include "move_matcher.hpp"

#include <algorithm>
#include <cstddef>
#include <vector>

namespace srcmove {

std::vector<move_match> greedy_match_1_to_1(const move_registry &mr) {
  std::vector<move_match> out;

  const auto &groups = mr.groups();

  // Upper bound: sum over groups of min(del, ins)
  std::size_t cap = 0;
  for (const auto &g : groups) {
    cap += std::min(g.del_count(), g.ins_count());
  }
  out.reserve(cap);

  for (const auto &g : groups) {
    const auto del_ids = mr.group_delete_ids(g);
    const auto ins_ids = mr.group_insert_ids(g);

    const std::size_t n = std::min(del_ids.size(), ins_ids.size());
    for (std::size_t k = 0; k < n; ++k) {
      out.push_back(move_match{del_ids[k], ins_ids[k]});
    }
  }

  return out;
}

std::vector<move_match> enumerate_all_pairs(const move_registry &mr,
                                            std::size_t hard_cap) {
  std::vector<move_match> out;

  for (const auto &g : mr.groups()) {
    const auto del_ids = mr.group_delete_ids(g);
    const auto ins_ids = mr.group_insert_ids(g);

    const std::size_t D = del_ids.size();
    const std::size_t I = ins_ids.size();
    if (D == 0 || I == 0)
      continue;

    // Watch for explosion: D×I
    if (hard_cap != SIZE_MAX) {
      const unsigned __int128 needed =
          static_cast<unsigned __int128>(D) * static_cast<unsigned __int128>(I);
      const unsigned __int128 remaining =
          (hard_cap > out.size()) ? (hard_cap - out.size()) : 0;
      if (needed > remaining)
        break;
    }

    for (std::size_t di = 0; di < D; ++di) {
      for (std::size_t ii = 0; ii < I; ++ii) {
        out.push_back(move_match{del_ids[di], ins_ids[ii]});
      }
    }
  }

  return out;
}

} // namespace srcmove
