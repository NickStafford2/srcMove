#include <cstddef>
#include <string>

#include "move_candidate.hpp"

namespace srcmove {

/*
 * Estimation that a particular move_candidate was intended as a move by the
 * developer.
 */
float move_candidate::calc_move_likelyhood(move_candidate original,
                                           move_candidate modified) {

  return 0.11;
}

std::size_t move_candidate::hash() { return 0; }
} // namespace srcmove
