#ifndef INCLUDED_MOVE_REGISTRY_DEBUG_HPP
#define INCLUDED_MOVE_REGISTRY_DEBUG_HPP

#include <iosfwd>

#include "move_registry.hpp"

namespace srcmove {

void print_registry_summary(const move_registry &mr, std::ostream &os);
void print_greedy_matches(const move_registry &mr, std::ostream &os);

} // namespace srcmove

#endif
