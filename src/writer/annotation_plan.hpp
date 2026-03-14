// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file annotation_plan.hpp
 */
#ifndef INCLUDED_MOVE_ANNOTATION_PLAN_HPP
#define INCLUDED_MOVE_ANNOTATION_PLAN_HPP

#include <cctype>
#include <string>
#include <vector>

#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_groups.hpp"

namespace srcmove {

struct move_tag {
  std::string              move_id;
  std::uint32_t            inserts = 0;
  std::uint32_t            deletes = 0;
  std::vector<std::string> partner_xpaths;
  std::string              raw_text;
};

// Map: start_idx (node index where diff:insert/delete START occurs) -> move tag
using tag_map = std::unordered_map<std::size_t, move_tag>;

tag_map build_move_tags(const content_groups     &groups,
                        const candidate_registry &registry,
                        const std::string         srcdiff_in_filename);

} // namespace srcmove

#endif
