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
#include "profile.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

namespace {

std::string match_kind_name(match_kind match) {
  switch (match) {
  case match_kind::exact:
    return "exact";
  case match_kind::type2:
    return "type2";
  case match_kind::unmatched:
    return "unmatched";
  }

  return "unmatched";
}

std::vector<std::string>
collect_group_xpaths(content_groups::id_view   ids,
                     const candidate_registry &registry) {
  std::vector<std::string> out;
  out.reserve(ids.size());

  for (id_t id : ids) {
    const move_candidate &candidate = registry.candidate(id);
    if (!candidate.xpath.empty()) {
      out.push_back(candidate.xpath);
    }
  }

  return out;
}

move_tag make_move_tag(const std::string              &move_id,
                       const std::string              &match_kind,
                       move_candidate::Kind            kind,
                       std::size_t                     ins_count,
                       std::size_t                     del_count,
                       const std::vector<std::string> &partner_xpaths,
                       const std::string              &raw_text) {
  move_tag tag;
  tag.move_id        = move_id;
  tag.match_kind     = match_kind;
  tag.kind           = kind;
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
                    const std::string              &match_kind,
                    std::size_t                     ins_count,
                    std::size_t                     del_count,
                    const std::vector<std::string> &partner_xpaths) {
  for (id_t id : ids) {
    const move_candidate &candidate = registry.candidate(id);

    tags.emplace(candidate.start_idx,
                 make_move_tag(move_id, match_kind, candidate.kind, ins_count,
                               del_count, partner_xpaths, candidate.raw_text));
  }
}

} // namespace

tag_map build_move_tags(const content_groups     &groups,
                        const candidate_registry &registry,
                        const std::string         srcdiff_in_filename,
                        profile_report           *profile) {

  scoped_profile_timer total_timer(profile, "annotation.plan_total");
  (void)srcdiff_in_filename;

  tag_map tags;

  {
    scoped_profile_timer timer(profile, "annotation.build_tags");
    // O(content groups + tagged candidate ids). XPaths are carried by candidates
    // from the initial parse, so tag building does not need another XML pass.
    for (const content_group &g : groups.groups()) {
      if (g.del_count() == 0 || g.ins_count() == 0)
        continue;

      const content_groups::id_view del_ids = groups.delete_ids(g);
      const content_groups::id_view ins_ids = groups.insert_ids(g);

      const std::vector<std::string> del_xpaths =
          collect_group_xpaths(del_ids, registry);
      const std::vector<std::string> ins_xpaths =
          collect_group_xpaths(ins_ids, registry);

      const std::string move_id    = get_uuid();
      const std::string match_kind = match_kind_name(g.match);

      add_group_tags(tags, del_ids, registry, move_id, match_kind, g.ins_count(),
                     g.del_count(), ins_xpaths);

      add_group_tags(tags, ins_ids, registry, move_id, match_kind, g.ins_count(),
                     g.del_count(), del_xpaths);
    }
  }

  return tags;
}

} // namespace srcmove
