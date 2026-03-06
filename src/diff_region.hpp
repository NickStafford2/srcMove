// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file diff_region.hpp
 *
 * Diff-region collection from srcDiff XML.
 *
 * Supports:
 * - single-file srcDiff:
 *     <unit filename="original.cpp|modified.cpp"> ... </unit>
 *
 * - multi-file archive srcDiff:
 *     <unit url="orig_dir|mod_dir">
 *       <unit filename="foo.cpp"> ... </unit>
 *       <unit filename="bar.hpp"> ... </unit>
 *     </unit>
 *
 * collect_all_regions() detects which form it is parsing from the root unit.
 */

#ifndef INCLUDED_DIFF_REGION_HPP
#define INCLUDED_DIFF_REGION_HPP
#include <cctype>
#include <string>
#include <vector>

#include <cassert>

#include "move_candidate.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

struct diff_region {
  move_candidate::Kind kind;
  std::string filename;

  std::size_t start_idx = 0;
  std::size_t end_idx = 0;

  std::string raw_text;
  std::string canonical_text;
  std::uint64_t hash = 0;

  std::size_t parent_id = static_cast<std::size_t>(-1);
  std::uint32_t depth = 0;
  bool has_diff_child = false;

  bool pre_marked = false;
  std::uint32_t existing_move_id = 0;
};

std::vector<diff_region> collect_all_regions(srcml_reader &reader);

} // namespace srcmove

#endif
