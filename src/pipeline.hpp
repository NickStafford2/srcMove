// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file pipeline.hpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */

#ifndef INCLUDED_MOVE_PIPELINE_HPP
#define INCLUDED_MOVE_PIPELINE_HPP

#include <vector>

#include "move_candidate.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

std::vector<move_candidate> collect_regions(srcml_reader &reader);

struct match {
  const move_candidate *del;
  const move_candidate *ins;
};

std::vector<match>
find_matching_regions_by_hash(const std::vector<move_candidate> &regions,
                              bool confirm_text_equality = true);

void first_pass(srcml_reader &reader);

} // namespace srcmove

#endif
