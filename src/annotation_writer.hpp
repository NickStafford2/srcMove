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

#include "move_region.hpp"
#include "move_registry/grouped_candidates.hpp"

namespace srcmove {

void annotate(std::vector<diff_region> regions, grouped_candidates mr,
              std::string srcdiff_in_filename,
              std::string srcdiff_out_filename);

} // namespace srcmove
#endif
