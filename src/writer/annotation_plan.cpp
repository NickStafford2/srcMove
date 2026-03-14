// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file annotation_plan.cpp
 */
#include <cctype>
#include <vector>

#include "annotation_plan.hpp"
#include "move_candidate.hpp"
#include "move_registry/content_groups.hpp"
#include "move_registry/uuid_generator.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

namespace {

using xpath_map = std::unordered_map<std::size_t, std::string>;

xpath_map collect_diff_region_xpaths(const std::string &in_filename) {
  srcml_reader reader(in_filename);

  xpath_map out;

  std::size_t i = 0;
  for (const srcml_node &node : reader) {
    if (node.is_start()) {
      const std::string fn = node.full_name();
      if (fn == "diff:insert" || fn == "diff:delete") {
        out.emplace(i, reader.get_current_xpath());
      }
    }
    ++i;
  }

  return out;
}

std::vector<std::string>
collect_group_xpaths(content_groups::id_view   ids,
                     const candidate_registry &registry,
                     const xpath_map          &xpaths) {
  std::vector<std::string> out;
  out.reserve(ids.size());

  for (id_t id : ids) {
    const move_candidate &candidate = registry.candidate(id);
    auto                  it        = xpaths.find(candidate.start_idx);
    if (it != xpaths.end()) {
      out.push_back(it->second);
    }
  }

  return out;
}

move_tag make_move_tag(const std::string              &move_id,
                       std::size_t                     ins_count,
                       std::size_t                     del_count,
                       const std::vector<std::string> &partner_xpaths,
                       const std::string              &raw_text) {
  move_tag tag;
  tag.move_id        = move_id;
  tag.inserts        = static_cast<std::uint32_t>(ins_count);
  tag.deletes        = static_cast<std::uint32_t>(del_count);
  tag.partner_xpaths = partner_xpaths;
  tag.raw_text       = raw_text;
  return tag;
}

void add_group_tags(tag_map                        &tags,
                    content_groups::id_view         ids,
                    const candidate_registry       &registry,
                    const std::string              &move_id,
                    std::size_t                     ins_count,
                    std::size_t                     del_count,
                    const std::vector<std::string> &partner_xpaths) {
  for (id_t id : ids) {
    const move_candidate &candidate = registry.candidate(id);

    tags.emplace(candidate.start_idx,
                 make_move_tag(move_id, ins_count, del_count, partner_xpaths,
                               candidate.raw_text));
  }
}

} // namespace

tag_map build_move_tags(const content_groups     &groups,
                        const candidate_registry &registry,
                        const std::string         srcdiff_in_filename) {

  const xpath_map xpaths = collect_diff_region_xpaths(srcdiff_in_filename);
  tag_map         tags;

  for (const content_group &g : groups.groups()) {
    if (g.del_count() == 0 || g.ins_count() == 0)
      continue;

    const content_groups::id_view del_ids = groups.delete_ids(g);
    const content_groups::id_view ins_ids = groups.insert_ids(g);

    const std::vector<std::string> del_xpaths =
        collect_group_xpaths(del_ids, registry, xpaths);
    const std::vector<std::string> ins_xpaths =
        collect_group_xpaths(ins_ids, registry, xpaths);

    const std::string move_id = get_uuid();

    add_group_tags(tags, del_ids, registry, move_id, g.ins_count(),
                   g.del_count(), ins_xpaths);

    add_group_tags(tags, ins_ids, registry, move_id, g.ins_count(),
                   g.del_count(), del_xpaths);
  }

  return tags;
}

} // namespace srcmove
