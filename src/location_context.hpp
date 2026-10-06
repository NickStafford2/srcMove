// SPDX-License-Identifier: GPL-3.0-only
#ifndef INCLUDED_LOCATION_CONTEXT_HPP
#define INCLUDED_LOCATION_CONTEXT_HPP

#include <cstddef>
#include <string>
#include <string_view>
#include <utility>

namespace srcmove {

// Owned, streaming-safe observations about one correspondence endpoint.
// Empty identifiers mean that the stream has not established reliable context;
// consumers must not infer location from XPath, line distance, or document order.
struct endpoint_location_context {
  std::string revision_file;
  // Legacy name for a structurally mapped named enclosing construct;
  // this does not imply behavioral or binding analysis.
  std::string semantic_container_id;
  std::string semantic_container_label;
  // Physical common source block or unbraced control body containing this
  // endpoint. A region inside a one-sided wrapper is not mapped by its
  // surrounding function alone.
  std::string structural_region_id;
  bool structural_region_mapped = false;
  // Nearest physically common enclosing region, looking through exclusive
  // wrappers only to test crossings of its actual common sibling statements.
  // This does not establish identity of any skipped one-sided region.
  std::string anchor_region_id;
  // Ranks in one shared ordered universe of complete unique common siblings.
  // [0, prefix_count) precedes the endpoint; [suffix_begin, count) follows it.
  // Comparing these ranks is valid only for the same nonempty anchor_region_id.
  std::size_t common_sibling_prefix_count = 0;
  std::size_t common_sibling_suffix_begin = 0;
  std::string previous_common_anchor_id;
  std::string next_common_anchor_id;
  std::size_t ancestor_summary_id = 0;
  bool semantic_container_mapped = false;
  bool ancestor_summary_reliable = false;
  bool ancestor_summary_interpretable = false;
  bool anchor_interval_reliable = false;
};

// srcDiff single-file unit names use old|new. Archive child units may instead
// contain one unchanged path, a one-sided old| or |new path, or distinct paths.
std::pair<std::string, std::string>
split_revision_filename(std::string_view combined_filename);

} // namespace srcmove

#endif
