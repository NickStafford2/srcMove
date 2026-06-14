#ifndef INCLUDED_MOVE_SUMMARY_HPP
#define INCLUDED_MOVE_SUMMARY_HPP

#include <cstddef>
#include <string>
#include <vector>

namespace srcmove {

struct move_entry {
  std::string              move_id;
  std::vector<std::string> from_xpaths;
  std::vector<std::string> to_xpaths;
  std::vector<std::string> from_raw_texts;
  std::vector<std::string> to_raw_texts;
};

struct group_kind_counts {
  std::size_t move_1_to_1    = 0;
  std::size_t moves_many     = 0;
  std::size_t delete_only    = 0;
  std::size_t insert_only    = 0;
  std::size_t copy_or_repeat = 0;
  std::size_t ambiguous      = 0;
};

struct match_kind_counts {
  std::size_t exact = 0;
  std::size_t type2 = 0;
};

struct summary {
  std::size_t             move_count = 0; // Backward-compatible alias for move_group_count.
  std::size_t             move_group_count = 0;
  std::size_t             move_pair_count = 0;
  std::vector<move_entry> moves;

  std::size_t annotated_regions = 0; // Backward-compatible alias for annotated_region_count.
  std::size_t annotated_region_count = 0;
  std::size_t regions_total     = 0;
  std::size_t candidates_total  = 0;
  std::size_t groups_total      = 0;
  group_kind_counts group_kinds;
  match_kind_counts match_kinds;
};

} // namespace srcmove
#endif
