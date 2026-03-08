// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file annotation.hpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */

#ifndef INCLUDED_MOVE_ANNOTATION_PLAN_HPP
#define INCLUDED_MOVE_ANNOTATION_PLAN_HPP

#include <cctype>
#include <string>
#include <vector>

#include "move_registry/candidate_registry.hpp"
#include "move_registry/move_groups.hpp"
#include "parse/diff_region.hpp"

namespace srcmove {

struct move_tag {
  std::uint32_t move_id = 0;
  std::uint32_t inserts = 0;
  std::uint32_t deletes = 0;
  std::vector<std::string> partner_xpaths;
  std::string raw_text;
};

// Map: start_idx (node index where diff:insert/delete START occurs) -> move tag
using tag_map = std::unordered_map<std::size_t, move_tag>;

std::uint32_t max_existing_move_id(const std::vector<diff_region> &regions);

tag_map
build_move_tags(const content_groups &groups,
                const candidate_registry &registry,
                const std::unordered_map<std::size_t, std::string> &xpaths,
                std::uint32_t start_id);

} // namespace srcmove

#endif
