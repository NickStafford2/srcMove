// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file annotation_plan.cpp
 */
#include <cctype>
#include <vector>

#include "annotation_plan.hpp"
#include "move_candidate.hpp"
#include "move_registry/content_groups.hpp"
#include "parse/diff_region.hpp"

namespace srcmove {

std::uint32_t max_existing_move_id(const std::vector<diff_region> &regions) {
  std::uint32_t mx = 0;
  for (const diff_region &r : regions) {
    if (r.pre_marked && r.existing_move_id > mx)
      mx = r.existing_move_id;
  }
  return mx;
}

tag_map
build_move_tags(const content_groups                               &groups,
                const candidate_registry                           &registry,
                const std::unordered_map<std::size_t, std::string> &xpaths,
                std::uint32_t                                       start_id) {

  tag_map       tags;
  std::uint32_t next_move_id = start_id;

  for (const content_group &g : groups.groups()) {
    if (g.del_count() == 0 || g.ins_count() == 0)
      continue;

    const std::uint32_t move_id = next_move_id++;

    std::vector<std::string> del_xpaths;
    std::vector<std::string> ins_xpaths;

    del_xpaths.reserve(g.del_count());
    ins_xpaths.reserve(g.ins_count());

    for (id_t did : groups.delete_ids(g)) {
      const move_candidate &d  = registry.candidate(did);
      auto                  it = xpaths.find(d.start_idx);
      if (it != xpaths.end()) {
        del_xpaths.push_back(it->second);
      }
    }

    for (id_t iid : groups.insert_ids(g)) {
      const move_candidate &ins = registry.candidate(iid);
      auto                  it  = xpaths.find(ins.start_idx);
      if (it != xpaths.end()) {
        ins_xpaths.push_back(it->second);
      }
    }

    for (id_t did : groups.delete_ids(g)) {
      const move_candidate &d = registry.candidate(did);

      move_tag tag;
      tag.move_id        = move_id;
      tag.inserts        = static_cast<std::uint32_t>(g.ins_count());
      tag.deletes        = static_cast<std::uint32_t>(g.del_count());
      tag.partner_xpaths = ins_xpaths;
      tag.raw_text       = d.raw_text;

      tags.emplace(d.start_idx, std::move(tag));
    }

    for (id_t iid : groups.insert_ids(g)) {
      const move_candidate &ins = registry.candidate(iid);

      move_tag tag;
      tag.move_id        = move_id;
      tag.inserts        = static_cast<std::uint32_t>(g.ins_count());
      tag.deletes        = static_cast<std::uint32_t>(g.del_count());
      tag.partner_xpaths = del_xpaths;
      tag.raw_text       = ins.raw_text;

      tags.emplace(ins.start_idx, std::move(tag));
    }
  }

  return tags;
}

} // namespace srcmove
