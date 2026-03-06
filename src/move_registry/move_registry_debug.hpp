#ifndef INCLUDED_MOVE_REGISTRY_DEBUG_HPP
#define INCLUDED_MOVE_REGISTRY_DEBUG_HPP

#include <iosfwd>

#include "grouped_candidates.hpp"

namespace srcmove {

void print_registry_summary(const grouped_candidates &mr, std::ostream &os);
void print_greedy_matches(const grouped_candidates &mr, std::ostream &os);

} // namespace srcmove

#endif
