#ifndef INCLUDED_MOVE_SUMMARY_HPP
#define INCLUDED_MOVE_SUMMARY_HPP
#include <cstddef>

namespace srcmove {

struct summary {
  std::size_t moves = 0;
  std::size_t annotated_regions = 0;
  std::size_t regions_total = 0;
  std::size_t candidates_total = 0;
  std::size_t groups_total = 0;
};

} // namespace srcmove
#endif
