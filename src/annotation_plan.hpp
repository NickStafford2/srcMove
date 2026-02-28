// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file annotation.hpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */

#ifndef INCLUDED_MOVE_ANNOTATION_HPP
#define INCLUDED_MOVE_ANNOTATION_HPP

#include <cctype>
#include <string>
#include <vector>

// uncomment to disable assert()
// #define NDEBUG
#include <cassert>

#include "move_region.hpp"
#include "move_registry.hpp"

namespace srcmove {

void annotate(std::vector<diff_region> regions, move_registry mr,
              std::string srcdiff_in_filename,
              std::string srcdiff_out_filename);
} // namespace srcmove

#endif
