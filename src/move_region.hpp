// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_region.hpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */

#ifndef INCLUDED_MOVE_REGION_HPP
#define INCLUDED_MOVE_REGION_HPP
#include <cctype>
#include <string>
#include <vector>

// uncomment to disable assert()
// #define NDEBUG
#include <cassert>

#include "move_candidate.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

// -----------------------------------------
// Region model collected from srcDiff
// -----------------------------------------
struct diff_region {
  move_candidate::Kind kind;
  std::string filename;

  std::size_t start_idx = 0; // node stream index of START tag
  std::size_t end_idx = 0;   // node stream index of END tag

  std::string full_text;  // reader.get_current_inner_text() at START
  std::uint64_t hash = 0; // hash(full_text) (optional for filtering)

  // nesting metadata
  std::size_t parent_id = static_cast<std::size_t>(-1);
  std::uint32_t depth = 0;
  bool has_diff_child = false;

  bool pre_marked = false;
  std::uint32_t existing_move_id = 0; // 0 means none/unknown
};

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
std::vector<diff_region> collect_all_regions(srcml_reader &reader);
std::vector<move_candidate> collect_regions(srcml_reader &reader);

} // namespace srcmove

#endif
