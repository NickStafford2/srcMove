// SPDX-License-Identifier: GPL-3.0-only
#ifndef INCLUDED_MOVE_REGISTRY_DEBUG_HPP
#define INCLUDED_MOVE_REGISTRY_DEBUG_HPP

#include <cstddef>
#include <iosfwd>

#include "candidate_registry.hpp"
#include "move_groups.hpp"

namespace srcmove {

void print_registry_summary(const candidate_registry &registry,
                            const content_groups     &groups,
                            std::ostream             &os);

void print_registry_by_file(const candidate_registry &registry,
                            std::ostream             &os);

void print_hash_buckets(const candidate_registry &registry,
                        std::ostream             &os,
                        std::size_t               max_buckets      = SIZE_MAX,
                        std::size_t               preview_per_side = 3);

void print_content_groups(const candidate_registry &registry,
                          const content_groups     &groups,
                          std::ostream             &os,
                          std::size_t               max_groups       = SIZE_MAX,
                          std::size_t               preview_per_side = 3);

void print_greedy_matches(const candidate_registry &registry,
                          const content_groups     &groups,
                          std::ostream             &os);

void print_full_registry_debug(const candidate_registry &registry,
                               const content_groups     &groups,
                               std::ostream             &os,
                               std::size_t               max_buckets      = 20,
                               std::size_t               max_groups       = 20,
                               std::size_t               preview_per_side = 3);

} // namespace srcmove

#endif
