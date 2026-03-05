// src/move_registry.cpp
// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_registry.cpp
 */
#include "move_registry.hpp"

#include <algorithm>
#include <cassert>
#include <iostream>
#include <utility>

#include "move_groups_builder.hpp"

namespace srcmove {

void move_registry::clear() {
  deletes_.clear();
  inserts_.clear();
  buckets_by_hash_.clear();
  groups_.clear();
}

void move_registry::reserve(std::size_t expected_deletes,
                            std::size_t expected_inserts) {
  deletes_.reserve(expected_deletes);
  inserts_.reserve(expected_inserts);

  // Hash bucket count is data-dependent, but reserving a rough upper bound
  // helps avoid rehashing during ingestion.
  buckets_by_hash_.reserve(expected_deletes + expected_inserts);
}

move_registry::id_t move_registry::add_delete(move_candidate del) {
  const id_t id = static_cast<id_t>(deletes_.size());
  const std::uint64_t h = del.hash;

  deletes_.push_back(std::move(del));
  auto &bucket = buckets_by_hash_[h];
  bucket.del_ids.push_back(id);
  return id;
}

move_registry::id_t move_registry::add_insert(move_candidate ins) {
  const id_t id = static_cast<id_t>(inserts_.size());
  const std::uint64_t h = ins.hash;

  inserts_.push_back(std::move(ins));
  auto &bucket = buckets_by_hash_[h];
  bucket.ins_ids.push_back(id);
  return id;
}

void move_registry::finalize(bool confirm_text_equality) {
  // Group building is intentionally delegated to a separate module.
  groups_ = build_groups_from_buckets(deletes_, inserts_, buckets_by_hash_,
                                      confirm_text_equality);
}

move_registry::id_view
move_registry::delete_ids(const content_group_compact &g) const noexcept {
  const std::uint32_t n = g.del_end - g.del_begin;
  if (n == 0)
    return id_view{nullptr, 0};

  return id_view{&groups_.group_del_ids[g.del_begin],
                 static_cast<std::size_t>(n)};
}

move_registry::id_view
move_registry::insert_ids(const content_group_compact &g) const noexcept {
  const std::uint32_t n = g.ins_end - g.ins_begin;
  if (n == 0)
    return id_view{nullptr, 0};

  return id_view{&groups_.group_ins_ids[g.ins_begin],
                 static_cast<std::size_t>(n)};
}

std::vector<move_match> move_registry::match_greedy_1_to_1() const {
  std::vector<move_match> out;

  // Upper bound: sum over groups of min(del, ins)
  std::size_t cap = 0;
  for (const auto &g : groups_.groups) {
    cap += std::min(g.del_count(), g.ins_count());
  }
  out.reserve(cap);

  for (const auto &g : groups_.groups) {
    const std::size_t n = std::min(g.del_count(), g.ins_count());
    for (std::size_t k = 0; k < n; ++k) {
      const id_t did =
          groups_.group_del_ids[g.del_begin + static_cast<std::uint32_t>(k)];
      const id_t iid =
          groups_.group_ins_ids[g.ins_begin + static_cast<std::uint32_t>(k)];
      out.push_back(move_match{did, iid});
    }
  }

  return out;
}

std::vector<move_match>
move_registry::enumerate_all_pairs(std::size_t hard_cap) const {
  std::vector<move_match> out;

  for (const auto &g : groups_.groups) {
    const std::size_t D = g.del_count();
    const std::size_t I = g.ins_count();
    if (D == 0 || I == 0)
      continue;

    // Watch for explosion: D×I
    if (hard_cap != SIZE_MAX) {
      const unsigned __int128 needed =
          static_cast<unsigned __int128>(D) * static_cast<unsigned __int128>(I);
      const unsigned __int128 remaining =
          (hard_cap > out.size()) ? (hard_cap - out.size()) : 0;
      if (needed > remaining)
        break;
    }

    for (std::uint32_t di = g.del_begin; di < g.del_end; ++di) {
      const id_t did = groups_.group_del_ids[di];
      for (std::uint32_t ii = g.ins_begin; ii < g.ins_end; ++ii) {
        const id_t iid = groups_.group_ins_ids[ii];
        out.push_back(move_match{did, iid});
      }
    }
  }

  return out;
}

void move_registry::debug(std::ostream &os) const {
  os << "move_registry:\n";
  os << "  deletes: " << deletes_.size() << "\n";
  os << "  inserts: " << inserts_.size() << "\n";
  os << "  hash buckets: " << buckets_by_hash_.size() << "\n";
  os << "  content groups: " << groups_.groups.size() << "\n";

  std::size_t move11 = 0, many = 0, delonly = 0, inonly = 0, copy = 0, amb = 0;
  for (const auto &g : groups_.groups) {
    switch (g.kind) {
    case group_kind::move_1_to_1:
      ++move11;
      break;
    case group_kind::moves_many:
      ++many;
      break;
    case group_kind::delete_only:
      ++delonly;
      break;
    case group_kind::insert_only:
      ++inonly;
      break;
    case group_kind::copy_or_repeat:
      ++copy;
      break;
    case group_kind::ambiguous:
      ++amb;
      break;
    }
  }

  os << "  group kinds:\n";
  os << "    move_1_to_1: " << move11 << "\n";
  os << "    moves_many: " << many << "\n";
  os << "    delete_only: " << delonly << "\n";
  os << "    insert_only: " << inonly << "\n";
  os << "    copy_or_repeat: " << copy << "\n";
  os << "    ambiguous: " << amb << "\n";
}

void move_registry::print_greedy_matches(std::ostream &os) const {

  // Debug/metrics about buckets/groups
  debug(os);

  // FAST baseline: 1-to-1 consumption inside each content group
  auto matches = match_greedy_1_to_1();

  const auto &dels = deletes();
  const auto &inss = inserts();

  os << "\n=== GREEDY MATCHES (DEL -> INS) ===\n";
  for (const auto &m : matches) {
    const auto &d = dels[m.del_id];
    const auto &ins = inss[m.ins_id];

    os << "DEL [" << d.start_idx << "," << d.end_idx << "] " << d.filename
       << "  ->  "
       << "INS [" << ins.start_idx << "," << ins.end_idx << "] " << ins.filename
       << "  hash=" << d.hash << "  chars(del)=" << d.full_text.size()
       << "  chars(ins)=" << ins.full_text.size() << "\n";
  }
}

move_registry build_move_registry(std::vector<move_candidate> &candidates) {

  move_registry mr;
  mr.reserve(/*expected_deletes=*/candidates.size(),
             /*expected_inserts=*/candidates.size());

  // Feed registry from collected regions
  for (auto &r : candidates) {
    if (r.kind == move_candidate::Kind::del) {
      mr.add_delete(std::move(r));
    } else {
      mr.add_insert(std::move(r));
    }
  }

  // Build groups (does equality confirmation + dedupe grouping if enabled)
  mr.finalize(/*confirm_text_equality=*/true);
  return mr;
}

} // namespace srcmove
