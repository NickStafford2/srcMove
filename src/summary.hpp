#ifndef INCLUDED_MOVE_SUMMARY_HPP
#define INCLUDED_MOVE_SUMMARY_HPP

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace srcmove {

struct move_entry {
  std::uint32_t move_id;
  std::vector<std::string> from_xpaths;
  std::vector<std::string> to_xpaths;
};

struct summary {
  std::size_t move_count = 0;
  std::vector<move_entry> moves;

  std::size_t annotated_regions = 0;
  std::size_t regions_total = 0;
  std::size_t candidates_total = 0;
  std::size_t groups_total = 0;
};

} // namespace srcmove
#endif
