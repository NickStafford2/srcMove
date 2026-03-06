// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file grouped_candidates_builder.hpp
 *
 * Registry for move/copy candidate detection.
 * This class owns candidates and build-time hash buckets.
 *
 * Goals:
 *  - Minimize allocations and string copies
 *  - Keep memory locality (contiguous storage)
 *  - Support duplicate-heavy buckets without D×I materialization unless asked
 *  - Enable multiple downstream modes:
 *      (1) fast 1-to-1 greedy pairing
 *      (2) emit all candidate pairs (optional, potentially large)
 *      (3) classify groups (move/copy/insert/delete/ambiguous) without pairing
 *
 * Notes:
 *  - This registry stores candidates by value in contiguous vectors.
 *  - Hash bucketing is done via unordered_map<hash, bucket>.
 *  - Equality confirmation is performed by partitioning each hash bucket into
 *    "content groups" keyed by exact full_text (or by a secondary hash).
 *
 *  - If you care deeply about performance, consider ensuring move_candidate's
 *    full_text is a string_view or an interned string. This implementation
 *    assumes move_candidate owns full_text (std::string) as in your project.
 *
 * Design goals:
 *  - stable, contiguous storage for candidates (good locality)
 *  - avoid materializing D×I pairs unless explicitly requested
 *  - expose ligktweight "views" of grouped candidates for downstream scoring
 */

#ifndef INCLUDED_MOVE_REGISTRY_GROUPED_CANDIDATES_BUILDER_HPP
#define INCLUDED_MOVE_REGISTRY_GROUPED_CANDIDATES_BUILDER_HPP

#include <cstdint>
#include <unordered_map>
#include <vector>

#include "grouped_candidates.hpp"
#include "move_buckets.hpp"
#include "move_candidate.hpp"

namespace srcmove {

class grouped_candidates_builder {
public:
  using id_t = candidate_id;

  void clear();
  void reserve(std::size_t expected_deletes, std::size_t expected_inserts);
  id_t add(move_candidate c);
  grouped_candidates finalize(bool confirm_text_equality);

  std::size_t bucket_count() const noexcept { return hash_index_.size(); }

private:
  // Build-time hash buckets.
  std::unordered_map<std::uint64_t, bucket_ids> hash_index_;

  std::vector<move_candidate> deletes_;
  std::vector<move_candidate> inserts_;

  id_t add_delete(move_candidate del);
  id_t add_insert(move_candidate ins);
};

} // namespace srcmove

#endif
