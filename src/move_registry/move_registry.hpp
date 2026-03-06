// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_registry.hpp
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

#ifndef INCLUDED_MOVE_REGISTRY_HPP
#define INCLUDED_MOVE_REGISTRY_HPP

#include <cstdint>
#include <unordered_map>
#include <vector>

#include "move_buckets.hpp"
#include "move_candidate.hpp"
#include "move_groups.hpp"

namespace srcmove {

struct move_match {
  candidate_id del_id; // index into deletes()
  candidate_id ins_id; // index into inserts()
};

class move_registry {
public:
  using id_t = candidate_id;

  void clear();

  void reserve(std::size_t expected_deletes, std::size_t expected_inserts);

  id_t add_delete(move_candidate del);
  id_t add_insert(move_candidate ins);

  /**
   * Build grouping structures from the ingested candidates + buckets.
   *
   * If confirm_text_equality is false, each hash bucket becomes one group.
   * If true, each hash bucket is refined into exact-text subgroups.
   *
   * After build_groups(), groups() is valid until the next clear() or
   * build_groups().
   */
  void build_groups(bool confirm_text_equality = true);

  const std::vector<move_candidate> &deletes() const noexcept {
    return deletes_;
  }
  const std::vector<move_candidate> &inserts() const noexcept {
    return inserts_;
  }

  const std::vector<content_group_compact> &groups() const noexcept {
    return groups_.groups;
  }

  // Lightweight view over a contiguous id range.
  struct id_view {
    const id_t *data = nullptr;
    std::size_t count = 0;

    const id_t *begin() const noexcept { return data; }
    const id_t *end() const noexcept { return data + count; }
    std::size_t size() const noexcept { return count; }

    const id_t &operator[](std::size_t i) const noexcept { return data[i]; }

    const id_t &at(std::size_t i) const {
      assert(i < count);
      return data[i];
    }
  };

  id_view group_delete_ids(const content_group_compact &g) const noexcept;
  id_view group_insert_ids(const content_group_compact &g) const noexcept;

  std::size_t delete_count() const noexcept { return deletes_.size(); }
  std::size_t insert_count() const noexcept { return inserts_.size(); }
  std::size_t bucket_count() const noexcept { return buckets_by_hash_.size(); }
  std::size_t group_count() const noexcept { return groups_.groups.size(); }

private:
  content_group_storage groups_;

  std::vector<move_candidate> deletes_;
  std::vector<move_candidate> inserts_;

  // Build-time hash buckets.
  std::unordered_map<std::uint64_t, bucket_ids> buckets_by_hash_;
};

move_registry build_move_registry(std::vector<move_candidate> &candidates);

} // namespace srcmove

#endif
