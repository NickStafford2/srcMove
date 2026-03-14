// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file content_group_builder.hpp
 *
 * Builds grouped views from the candidate registry.
 *
 * This is a pure "derived state" step in the architecture.
 *
 * Input:
 *   candidate_registry (authoritative candidate storage)
 *
 * Output:
 *   content_groups (compact grouped snapshot)
 *
 * Responsibilities:
 * - partition candidates by content hash
 * - optionally confirm exact text equality
 * - classify group types (1-1 move, many-many, delete-only, etc.)
 *
 * The builder does NOT mutate the registry.
 */

#ifndef INCLUDED_CONTENT_GROUP_BUILDER_HPP
#define INCLUDED_CONTENT_GROUP_BUILDER_HPP

#include "candidate_registry.hpp"
#include "content_groups.hpp"

namespace srcmove {

/**
 * Build a grouped snapshot of the current registry state.
 *
 * confirm_text_equality:
 *   false → one group per hash bucket
 *   true  → split buckets by exact text equality
 */
content_groups build_content_groups(const candidate_registry &registry,
                                    bool confirm_text_equality = true);

} // namespace srcmove

#endif
