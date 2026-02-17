#include <cstddef>
#include <string>

#include "move_candidate.hpp"

namespace srcmove {

move_candidate_pair::move_candidate_pair(move_candidate original,
                                         move_candidate modified)
    : original(original), modified(modified) {}

/*
 * Estimation that a particular move_candidate was intended as a move by the
 * developer.
 */
float move_candidate_pair::calc_move_likelyhood(move_candidate original,
                                                move_candidate modified) {

  return 0.11;
}

std::size_t move_candidate_pair::hash() { return 0; }

std::string move_candidate_pair::debug_id() { return "todo later."; }
} // namespace srcmove
