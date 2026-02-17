#include <cstddef>
#include <string>

#include "move_candidate.hpp"

namespace srcmove {

move_candidate::move_candidate(move_candidate_part original,
                               move_candidate_part modified)
    : original(original), modified(modified) {}

/*
 * Estimation that a particular move_candidate was intended as a move by the
 * developer.
 */
float move_candidate::calc_move_likelyhood(move_candidate_part original,
                                           move_candidate_part modified) {

  return 0.11;
}

std::size_t move_candidate::hash() { return 0; }

std::string move_candidate::debug_id() { return "todo later."; }
} // namespace srcmove
