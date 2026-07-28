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
 * - optionally run refined exact/Type-2 grouping and selection
 * - classify group types (1-1 move, many-many, delete-only, etc.)
 *
 * The builder does NOT mutate the registry.
 */

#ifndef INCLUDED_CONTENT_GROUP_BUILDER_HPP
#define INCLUDED_CONTENT_GROUP_BUILDER_HPP

#include "candidate_registry.hpp"
#include "content_groups.hpp"

namespace srcmove {

class profile_report;

enum class content_grouping_mode {
  hash_bucket_only,
  refined,
};

/**
 * Build a grouped snapshot of the current registry state.
 *
 * Mode:
 * - hash_bucket_only: one group per content-hash bucket; no exact text split,
 *   selection suppression, or Type-2 recovery.
 * - refined: split buckets by exact canonical text, select non-overlapping
 *   exact groups first, recover eligible one-to-one Type-2 groups, then emit
 *   unmatched leftovers.
 */
content_groups build_content_groups(const candidate_registry &registry,
                                    content_grouping_mode mode =
                                        content_grouping_mode::refined,
                                    profile_report *profile = nullptr);

} // namespace srcmove

#endif
