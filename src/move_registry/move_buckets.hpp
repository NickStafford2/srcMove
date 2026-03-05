// src/move_buckets.hpp
// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_buckets.hpp
 *
 * Build-time hash buckets used by move_registry grouping.
 */
#ifndef INCLUDED_MOVE_BUCKETS_HPP
#define INCLUDED_MOVE_BUCKETS_HPP

#include <cstdint>
#include <vector>

namespace srcmove {

// Shared id type for candidates stored in the registry.
using candidate_id = std::uint32_t;

// Hash bucket used during ingestion: ids only (indices into deletes/inserts).
struct bucket_ids {
  std::vector<candidate_id> del_ids;
  std::vector<candidate_id> ins_ids;
};

} // namespace srcmove

#endif
