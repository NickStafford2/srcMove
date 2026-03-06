// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file annotation.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include <cctype>
#include <vector>

#include "annotation_plan.hpp"
#include "move_candidate.hpp"
#include "move_region.hpp"
#include "move_registry/grouped_candidates.hpp"

namespace srcmove {

std::uint32_t max_existing_move_id(const std::vector<diff_region> &regions) {
  std::uint32_t mx = 0;
  for (const auto &r : regions) {
    if (r.pre_marked && r.existing_move_id > mx)
      mx = r.existing_move_id;
  }
  return mx;
}

tag_map build_move_tags(const grouped_candidates &mr, std::uint32_t start_id) {
  tag_map tags;

  std::uint32_t next_move_id = start_id;

  for (const auto &g : mr.groups()) {
    if (g.del_count() == 0 || g.ins_count() == 0)
      continue; // only groups with both sides get a move id

    const std::uint32_t move_id = next_move_id++;

    // Apply to all deletes in group
    for (auto did : mr.group_delete_ids(g)) {
      const auto &d = mr.deletes()[did];
      tags.emplace(d.start_idx, move_tag{move_id});
    }

    // Apply to all inserts in group
    for (auto iid : mr.group_insert_ids(g)) {
      const auto &ins = mr.inserts()[iid];
      tags.emplace(ins.start_idx, move_tag{move_id});
    }
  }

  return tags;
}

} // namespace srcmove
