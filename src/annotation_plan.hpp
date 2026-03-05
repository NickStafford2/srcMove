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

#include "move_region.hpp"
#include "move_registry/move_registry.hpp"

namespace srcmove {

struct move_tag {
  std::uint32_t move_id;
};

// Map: start_idx (node index where diff:insert/delete START occurs) -> move tag
using tag_map = std::unordered_map<std::size_t, move_tag>;

std::uint32_t max_existing_move_id(const std::vector<diff_region> &regions);

tag_map build_move_tags(const move_registry &mr, std::uint32_t start_id);

} // namespace srcmove

#endif
