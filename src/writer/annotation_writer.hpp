// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file annotation_writer.hpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#ifndef INCLUDED_MOVE_ANNOTATION_WRITER_HPP
#define INCLUDED_MOVE_ANNOTATION_WRITER_HPP

#include <cctype>
#include <string>
#include <vector>

#include "move_registry/candidate_registry.hpp"
#include "move_registry/move_groups.hpp"
#include "parse/diff_region.hpp"
#include "summary.hpp"

namespace srcmove {

std::vector<move_entry> annotate(const std::vector<diff_region> &regions,
                                 const candidate_registry &registry,
                                 const content_groups &groups,
                                 const std::string &srcdiff_in_filename,
                                 const std::string &srcdiff_out_filename);

} // namespace srcmove
#endif
