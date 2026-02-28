// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_region.hpp
 *
 */

#ifndef INCLUDED_MOVE_REGION_FILTER_HPP
#define INCLUDED_MOVE_REGION_FILTER_HPP
#include <cctype>
#include <vector>

#include "move_candidate.hpp"
#include "move_region.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

// -----------------------------------------
// Region model collected from srcDiff
// -----------------------------------------
;

// -----------------------------------------
// Filtering policy (choose move units)
// -----------------------------------------
enum class region_filter_policy {
  leaf_only,      // regions with no diff children (usually best for moves)
  top_level_only, // parent == none (outer wrappers / hunks)
  all_regions     // everything
};

struct region_filter_options {
  region_filter_policy policy = region_filter_policy::leaf_only;
  // Common practical filters:
  bool drop_whitespace_only = true;
  bool skip_pre_marked = true;
  std::size_t min_chars = 1; // after whitespace-only check (still raw chars)
};

region_filter_options get_default_filter_options();

std::vector<move_candidate>
filter_regions_for_registry(const std::vector<diff_region> &regions,
                            const region_filter_options &opt);
std::vector<move_candidate> collect_regions(srcml_reader &reader);

} // namespace srcmove

#endif
