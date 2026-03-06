// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file candidate_registry.hpp
 *
 * Authoritative storage for move candidates across all currently loaded files.
 *
 * Broadly:
 * - owns every candidate record
 * - tracks which candidates came from which file
 * - maintains hash buckets for fast delete/insert lookup by content hash
 *
 * Important design idea:
 * - this is the persistent stateful core of the move-detection pipeline
 * - grouping and matching are NOT owned here
 * - groups are rebuilt later as a derived snapshot from the registry
 *
 * Incremental workflow:
 * - add candidates for a file as it is read
 * - remove candidates when a file is reprocessed or replaced
 * - rebuild derived grouped views from the registry's current active state
 *
 * Performance notes:
 * - candidates are stored contiguously in a single vector
 * - buckets store candidate ids, not copies of candidates
 * - removals are handled by marking records inactive, then rebuilding buckets
 *   for correctness and simplicity
 */
#ifndef INCLUDED_CANDIDATE_REGISTRY_HPP
#define INCLUDED_CANDIDATE_REGISTRY_HPP

#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "move_buckets.hpp"
#include "move_candidate.hpp"

namespace srcmove {

class candidate_registry {
public:
  using id_t = candidate_id;
  using file_key = std::string;

  struct candidate_record {
    move_candidate candidate;
    bool active = true;
  };

  candidate_registry() = default;

  // Reserve storage up front when approximate candidate volume is known.
  void reserve(std::size_t expected_candidates,
               std::size_t expected_bucket_count = 0);

  // Drop all registry state.
  void clear();

  /**
   * Add candidates produced from parsing one file.
   *
   * Each candidate receives a new global candidate_id and is immediately
   * inserted into the appropriate hash bucket for later grouping.
   */
  void add_candidates_for_file(const file_key &file,
                               std::vector<move_candidate> candidates);

  /**
   * Remove all candidates that originated from a specific file.
   *
   * Implementation detail:
   * - candidates are marked inactive
   * - buckets are rebuilt from remaining active candidates
   *
   * This keeps removal logic simple and avoids expensive vector erases.
   */
  void remove_candidates_for_file(const file_key &file);

  /**
   * Replace a file’s candidates in one step.
   *
   * Equivalent to:
   *   remove_candidates_for_file(file)
   *   add_candidates_for_file(file, new_candidates)
   */
  void replace_candidates_for_file(const file_key &file,
                                   std::vector<move_candidate> candidates);

  bool has_file(const file_key &file) const;
  std::size_t file_count() const noexcept;

  // ----- Candidate access -----

  // Raw storage of all records (active + inactive).
  const std::vector<candidate_record> &records() const noexcept {
    return records_;
  }

  // Access full record by id.
  const candidate_record &record(id_t id) const noexcept {
    return records_[id];
  }

  // Most common lookup: get the candidate itself.
  const move_candidate &candidate(id_t id) const noexcept {
    return records_[id].candidate;
  }

  bool is_active(id_t id) const noexcept { return records_[id].active; }

  /**
   * Hash buckets used for grouping.
   *
   * Key: content hash
   * Value: candidate ids partitioned into delete vs insert sides.
   */
  const std::unordered_map<std::uint64_t, bucket_ids> &
  hash_buckets() const noexcept {
    return hash_buckets_;
  }

  const std::vector<id_t> *file_candidate_ids(const file_key &file) const;

  std::size_t total_record_count() const noexcept { return records_.size(); }
  std::size_t active_candidate_count() const noexcept { return active_count_; }
  std::size_t bucket_count() const noexcept { return hash_buckets_.size(); }

private:
  // Append a candidate to storage and assign it a new id.
  id_t append_candidate(move_candidate candidate);

  // Insert candidate id into the correct hash bucket.
  void activate_in_bucket(id_t id);

  // Rebuild buckets after removals.
  void rebuild_hash_buckets();

  std::vector<candidate_record> records_;

  // Which candidates came from which file.
  std::unordered_map<file_key, std::vector<id_t>> file_to_candidate_ids_;

  // Hash -> delete/insert candidate ids
  std::unordered_map<std::uint64_t, bucket_ids> hash_buckets_;

  std::size_t active_count_ = 0;
};

} // namespace srcmove

#endif
