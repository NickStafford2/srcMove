#ifndef INCLUDED_MOVE_CANDIDATE_HPP
#define INCLUDED_MOVE_CANDIDATE_HPP

#include <cstddef>
#include <string>

#include "move_candidate_part.hpp"

namespace srcmove {

struct move_candidate {
  move_candidate_part original;
  move_candidate_part modified;

  /*
   * Estimation that a particular move_candidate was intended as a move by the
   * developer.
   */
  float calc_move_likelyhood(move_candidate_part original,
                             move_candidate_part modified);
  std::size_t hash();
  std::string debug_id();
};

} // namespace srcmove
#endif
