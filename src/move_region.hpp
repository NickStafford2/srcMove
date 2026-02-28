// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_region.hpp
 *
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

// Region model collected from srcDiff
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

std::vector<diff_region> collect_all_regions(srcml_reader &reader);

} // namespace srcmove

#endif
