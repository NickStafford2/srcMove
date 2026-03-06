// SPDX-License-Identifier: GPL-3.0-only
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

  void reserve(std::size_t expected_candidates,
               std::size_t expected_bucket_count = 0);

  void clear();

  // Incremental update API
  void add_candidates_for_file(const file_key &file,
                               std::vector<move_candidate> candidates);

  void remove_candidates_for_file(const file_key &file);

  void replace_candidates_for_file(const file_key &file,
                                   std::vector<move_candidate> candidates);

  bool has_file(const file_key &file) const;
  std::size_t file_count() const noexcept;

  // Access to authoritative candidate state
  const std::vector<candidate_record> &records() const noexcept {
    return records_;
  }

  const candidate_record &record(id_t id) const noexcept {
    return records_[id];
  }

  const move_candidate &candidate(id_t id) const noexcept {
    return records_[id].candidate;
  }

  bool is_active(id_t id) const noexcept { return records_[id].active; }

  const std::unordered_map<std::uint64_t, bucket_ids> &
  hash_buckets() const noexcept {
    return hash_buckets_;
  }

  const std::vector<id_t> *file_candidate_ids(const file_key &file) const;

  std::size_t total_record_count() const noexcept { return records_.size(); }
  std::size_t active_candidate_count() const noexcept { return active_count_; }
  std::size_t bucket_count() const noexcept { return hash_buckets_.size(); }

private:
  id_t append_candidate(move_candidate candidate);
  void activate_in_bucket(id_t id);
  void deactivate_in_bucket(id_t id);

  std::vector<candidate_record> records_;
  std::unordered_map<file_key, std::vector<id_t>> file_to_candidate_ids_;
  std::unordered_map<std::uint64_t, bucket_ids> hash_buckets_;
  std::size_t active_count_ = 0;
};

} // namespace srcmove

#endif
