// SPDX-License-Identifier: GPL-3.0-only
#include "candidate_registry.hpp"
#include "move_candidate.hpp"
#include "move_registry/move_buckets.hpp"

#include <utility>
#include <vector>

namespace srcmove {

void candidate_registry::reserve(std::size_t expected_candidates,
                                 std::size_t expected_bucket_count) {
  records_.reserve(expected_candidates);

  if (expected_bucket_count != 0) {
    hash_buckets_.reserve(expected_bucket_count);
  } else {
    hash_buckets_.reserve(expected_candidates);
  }
}

void candidate_registry::clear() {
  records_.clear();
  file_to_candidate_ids_.clear();
  hash_buckets_.clear();
  active_count_ = 0;
}

bool candidate_registry::has_file(const file_key &file) const {
  return file_to_candidate_ids_.find(file) != file_to_candidate_ids_.end();
}

std::size_t candidate_registry::file_count() const noexcept {
  return file_to_candidate_ids_.size();
}

const std::vector<candidate_registry::id_t> *
candidate_registry::file_candidate_ids(const file_key &file) const {
  auto it = file_to_candidate_ids_.find(file);
  if (it == file_to_candidate_ids_.end()) {
    return nullptr;
  }
  return &it->second;
}

void candidate_registry::add_candidates_for_file(
    const file_key &file, std::vector<move_candidate> candidates) {

  std::vector<unsigned int> &ids = file_to_candidate_ids_[file];
  ids.reserve(ids.size() + candidates.size());

  for (move_candidate &candidate : candidates) {
    const id_t id = append_candidate(std::move(candidate));
    ids.push_back(id);
  }
}

void candidate_registry::remove_candidates_for_file(const file_key &file) {
  auto it = file_to_candidate_ids_.find(file);
  if (it == file_to_candidate_ids_.end()) {
    return;
  }

  for (id_t id : it->second) {
    if (!records_[id].active) {
      continue;
    }

    records_[id].active = false;
    --active_count_;
  }

  file_to_candidate_ids_.erase(it);
  rebuild_hash_buckets();
}

void candidate_registry::replace_candidates_for_file(
    const file_key &file, std::vector<move_candidate> candidates) {
  remove_candidates_for_file(file);
  add_candidates_for_file(file, std::move(candidates));
}

candidate_registry::id_t
candidate_registry::append_candidate(move_candidate candidate) {
  const id_t id = static_cast<id_t>(records_.size());
  records_.push_back(candidate_record{std::move(candidate), true});
  ++active_count_;
  activate_in_bucket(id);
  return id;
}

void candidate_registry::activate_in_bucket(id_t id) {
  const move_candidate &candidate = records_[id].candidate;
  bucket_ids           &bucket    = hash_buckets_[candidate.hash];

  if (candidate.kind == move_candidate::Kind::del) {
    bucket.del_ids.push_back(id);
  } else {
    bucket.ins_ids.push_back(id);
  }
}

void candidate_registry::rebuild_hash_buckets() {
  hash_buckets_.clear();
  hash_buckets_.reserve(active_count_);

  for (id_t id = 0; id < static_cast<id_t>(records_.size()); ++id) {
    if (!records_[id].active) {
      continue;
    }
    activate_in_bucket(id);
  }
}

} // namespace srcmove
