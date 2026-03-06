// SPDX-License-Identifier: GPL-3.0-only
#ifndef INCLUDED_MOVE_REGISTRY_DEBUG_HPP
#define INCLUDED_MOVE_REGISTRY_DEBUG_HPP

#include <iosfwd>

#include "candidate_registry.hpp"
#include "move_groups.hpp"

namespace srcmove {

void print_registry_summary(const candidate_registry &registry,
                            const content_groups &groups, std::ostream &os);

void print_greedy_matches(const candidate_registry &registry,
                          const content_groups &groups, std::ostream &os);

} // namespace srcmove

#endif
