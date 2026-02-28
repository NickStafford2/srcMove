// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_registry.hpp
 *
 * Registry for move/copy candidate detection.
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
#include <iosfwd>
#include <unordered_map>
#include <vector>

#include "move_candidate.hpp"

namespace srcmove {

struct move_match {
  std::uint32_t del_id; // index into deletes()
  std::uint32_t ins_id; // index into inserts()
};

enum class group_kind : std::uint8_t {
  // After equality confirmation within a hash bucket:
  // del_count and ins_count describe what exists for the same exact content.
  move_1_to_1,    // del=1 ins=1
  moves_many,     // del=k ins=k (k>1) ambiguous pairing
  delete_only,    // del>0 ins=0
  insert_only,    // del=0 ins>0
  copy_or_repeat, // del>0 ins>del or del==0 ins>0 (policy-dependent)
  ambiguous       // everything else / policy-specific
};

/**
 * A compact view over one "content group".
 *
 * A content group represents candidates that share the same primary hash and,
 * when exact matching is enabled, the same exact full_text.
 *
 * The group does not store ids directly; instead it stores index ranges into
 * internal flat arrays (group_del_ids_ / group_ins_ids_). This keeps the group
 * itself small and avoids iterator invalidation issues.
 */
struct content_group_view {
  std::uint64_t content_hash; // primary bucket key (fast_hash_raw)
  std::uint32_t group_id;     // stable id within registry instance

  // ranges into internal vectors of ids (not iterators to avoid invalidation)
  std::uint32_t del_begin, del_end; // [begin, end)
  std::uint32_t ins_begin, ins_end; // [begin, end)

  // classification after finalize()
  group_kind kind;

  std::size_t del_count() const {
    return static_cast<std::size_t>(del_end - del_begin);
  }
  std::size_t ins_count() const {
    return static_cast<std::size_t>(ins_end - ins_begin);
  }
};

class move_registry {
public:
  using id_t = std::uint32_t;

  // Clear all stored state.
  void clear();

  // Optional: reduce reallocations during ingestion.
  void reserve(std::size_t expected_deletes, std::size_t expected_inserts);

  // Add candidates (the registry owns them).
  id_t add_delete(move_candidate del);
  id_t add_insert(move_candidate ins);

  /**
   * Build grouping structures from the ingested candidates.
   *
   * If confirm_text_equality is false, each hash bucket becomes one group.
   * If true, each hash bucket is refined into exact-text subgroups, which
   * prevents false matches due to hash collisions.
   *
   * After finalize(), groups() is valid until the next clear() or finalize().
   *
   * builds the internal grouping structure that all matching logic depends on
   * It constructs:
   *   group_del_ids_ (flat array of delete ids)
   *   group_ins_ids_ (flat array of insert ids)
   *   groups_        (vector of content_group_view)
   */
  void finalize(bool confirm_text_equality = true);

  // Accessors for stored candidates (contiguous, stable until clear()).
  const std::vector<move_candidate> &deletes() const noexcept {
    return deletes_;
  }
  const std::vector<move_candidate> &inserts() const noexcept {
    return inserts_;
  }

  // Group views after finalize().
  const std::vector<content_group_view> &groups() const noexcept {
    return groups_;
  }

  // Fast baseline: within each content group, pair min(del_count, ins_count)
  // greedily in insertion order (1-to-1 consumption). O(total candidates).
  //
  // This DOES NOT materialize D×I; it picks a set of pairs.
  std::vector<move_match> match_greedy_1_to_1() const;

  // Optional: emit all candidate pairs (cartesian product) within each content
  // group. Can be huge if duplicates are heavy.
  std::vector<move_match>
  enumerate_all_pairs(std::size_t hard_cap = SIZE_MAX) const;

  // Debug/metrics.
  void debug(std::ostream &os) const;

private:
  // Buckets by hash during build phase: store ids (indices) only.
  struct hash_bucket {
    std::vector<id_t> del_ids;
    std::vector<id_t> ins_ids;
  };

  // During finalize() we create "flat" id lists for each content group to allow
  // stable views with (begin,end) ranges.
  //
  // groups_ refers into these arrays:
  std::vector<id_t> group_del_ids_;
  std::vector<id_t> group_ins_ids_;
  std::vector<content_group_view> groups_;

  // Owned candidates.
  std::vector<move_candidate> deletes_;
  std::vector<move_candidate> inserts_;

  // Build-time hash buckets.
  std::unordered_map<std::uint64_t, hash_bucket> by_hash_;

private:
  // Helper: classify group based on counts (policy can evolve later).
  static group_kind classify_counts(std::size_t del_count,
                                    std::size_t ins_count);

  // Helper: append ids and create group view.
  void add_group(std::uint64_t content_hash, const std::vector<id_t> &del_ids,
                 const std::vector<id_t> &ins_ids);
};

} // namespace srcmove

#endif
