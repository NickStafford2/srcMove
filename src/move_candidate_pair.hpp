#ifndef INCLUDED_MOVE_CANDIDATE_PAIR_HPP
#define INCLUDED_MOVE_CANDIDATE_PAIR_HPP

#include <cstddef>
#include <string>

#include "move_candidate.hpp"

namespace srcmove {

struct move_candidate_pair {

  move_candidate_pair(move_candidate original, move_candidate modified);

  move_candidate original;
  move_candidate modified;

  /*
   * Estimation that a particular move_candidate was intended as a move by the
   * developer.
   */
  float calc_move_likelyhood(move_candidate original, move_candidate modified);

  std::size_t hash();
  std::string debug_id();
};

} // namespace srcmove
#endif
