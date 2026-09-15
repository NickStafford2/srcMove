// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file region_filter.hpp
 *
 */

#ifndef INCLUDED_MOVE_REGION_FILTER_HPP
#define INCLUDED_MOVE_REGION_FILTER_HPP
#include <cctype>
#include <vector>

#include "move_candidate.hpp"
#include "parse/diff_region.hpp"
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

enum class minimum_move_granularity {
  statement,
  fragment,
};

struct region_filter_options {
  region_filter_policy policy = region_filter_policy::leaf_only;
  // Common practical filters:
  bool        drop_whitespace_only = true;
  bool        skip_pre_marked      = false;
  bool        expand_structural_children = true;
  std::size_t min_chars = 2; // after whitespace-only check (still raw chars)
  minimum_move_granularity min_granularity =
      minimum_move_granularity::statement;
  // Four srcML lexical text events admit useful expressions such as `x = y;`
  // while rejecting isolated tokens and low-information control statements.
  std::size_t min_statement_tokens = 4;
};

region_filter_options get_default_filter_options();

std::vector<move_candidate>
filter_regions_for_registry(const std::vector<diff_region> &regions,
                            const region_filter_options    &opt);
std::vector<move_candidate> collect_regions(srcml_reader &reader);

} // namespace srcmove

#endif
