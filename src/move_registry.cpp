// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_registry.cpp
 */

#include "move_registry.hpp"

#include <algorithm>
#include <cassert>
#include <iostream>
#include <string_view>
#include <utility>

namespace srcmove {

void move_registry::clear() {
  deletes_.clear();
  inserts_.clear();
  by_hash_.clear();

  group_del_ids_.clear();
  group_ins_ids_.clear();
  groups_.clear();
}

void move_registry::reserve(std::size_t expected_deletes,
                            std::size_t expected_inserts) {
  deletes_.reserve(expected_deletes);
  inserts_.reserve(expected_inserts);

  // Hash bucket count is data-dependent, but reserving a rough upper bound
  // helps avoid rehashing during ingestion.
  by_hash_.reserve(expected_deletes + expected_inserts);
}

move_registry::id_t move_registry::add_delete(move_candidate del) {
  const id_t id = static_cast<id_t>(deletes_.size());
  const std::uint64_t h = del.hash;

  deletes_.push_back(std::move(del));
  auto &bucket = by_hash_[h];
  bucket.del_ids.push_back(id);
  return id;
}

move_registry::id_t move_registry::add_insert(move_candidate ins) {
  const id_t id = static_cast<id_t>(inserts_.size());
  const std::uint64_t h = ins.hash;

  inserts_.push_back(std::move(ins));
  auto &bucket = by_hash_[h];
  bucket.ins_ids.push_back(id);
  return id;
}

group_kind move_registry::classify_counts(std::size_t del_count,
                                          std::size_t ins_count) {
  if (del_count == 0 && ins_count == 0) {
    // A correctly-constructed group should never be empty on both sides.
    return group_kind::ambiguous;
  }
  if (del_count > 0 && ins_count == 0)
    return group_kind::delete_only;
  if (del_count == 0 && ins_count > 0)
    return group_kind::insert_only;

  // Both sides exist.
  if (del_count == 1 && ins_count == 1)
    return group_kind::move_1_to_1;

  if (del_count == ins_count && del_count > 1)
    return group_kind::moves_many;

  // If inserts exceed deletes, it might be copy/paste or repeated insertion.
  // If deletes exceed inserts, it might be multiple removals with one
  // remaining.
  return group_kind::copy_or_repeat;
}

void move_registry::add_group(std::uint64_t content_hash,
                              const std::vector<id_t> &del_ids,
                              const std::vector<id_t> &ins_ids) {
  const std::uint32_t group_id = static_cast<std::uint32_t>(groups_.size());

  const std::uint32_t del_begin =
      static_cast<std::uint32_t>(group_del_ids_.size());
  group_del_ids_.insert(group_del_ids_.end(), del_ids.begin(), del_ids.end());
  const std::uint32_t del_end =
      static_cast<std::uint32_t>(group_del_ids_.size());

  const std::uint32_t ins_begin =
      static_cast<std::uint32_t>(group_ins_ids_.size());
  group_ins_ids_.insert(group_ins_ids_.end(), ins_ids.begin(), ins_ids.end());
  const std::uint32_t ins_end =
      static_cast<std::uint32_t>(group_ins_ids_.size());

  const group_kind kind = classify_counts(del_ids.size(), ins_ids.size());

  groups_.push_back(content_group_view{
      content_hash,
      group_id,
      del_begin,
      del_end,
      ins_begin,
      ins_end,
      kind,
  });
}

void move_registry::finalize(bool confirm_text_equality) {
  group_del_ids_.clear();
  group_ins_ids_.clear();
  groups_.clear();

  groups_.reserve(by_hash_.size());

  // Fast path: one group per hash bucket.
  if (!confirm_text_equality) {
    for (const auto &[h, bucket] : by_hash_) {
      add_group(h, bucket.del_ids, bucket.ins_ids);
    }
    return;
  }

  // confirm_text_equality == true:
  // Split each hash bucket into subgroups by exact full_text.
  //
  // To avoid copying strings, key on std::string_view referencing candidates'
  // stored full_text.
  // This is safe because deletes_/inserts_ own the strings for the lifetime of
  // the registry (until clear()).
  struct sv_hash {
    std::size_t operator()(std::string_view s) const noexcept {
      // Use std::hash<string_view> (fast). For fewer collisions you can use
      // a stronger hash, but equality check remains exact anyway.
      return std::hash<std::string_view>{}(s);
    }
  };

  static const std::vector<id_t> kEmpty;

  for (const auto &[h, bucket] : by_hash_) {
    // Map exact content -> ids within this hash bucket.
    std::unordered_map<std::string_view, std::vector<id_t>, sv_hash>
        del_by_text;
    std::unordered_map<std::string_view, std::vector<id_t>, sv_hash>
        ins_by_text;

    del_by_text.reserve(bucket.del_ids.size());
    ins_by_text.reserve(bucket.ins_ids.size());

    for (id_t did : bucket.del_ids) {
      const auto &d = deletes_[did];
      del_by_text[std::string_view(d.full_text)].push_back(did);
    }
    for (id_t iid : bucket.ins_ids) {
      const auto &ins = inserts_[iid];
      ins_by_text[std::string_view(ins.full_text)].push_back(iid);
    }

    // Union of keys from both maps: build groups for each distinct text.
    // We do it by iterating deletes' keys, then inserts' keys not seen.
    std::unordered_map<std::string_view, bool, sv_hash> seen;
    seen.reserve(del_by_text.size() + ins_by_text.size());

    // Build groups for delete keys first.
    for (auto &[text, dels] : del_by_text) {
      (void)seen.emplace(text, true);
      auto it = ins_by_text.find(text);
      if (it != ins_by_text.end()) {
        add_group(h, dels, it->second);
      } else {
        static const std::vector<id_t> empty;
        add_group(h, dels, empty);
      }
    }

    // Then groups for insert-only keys.
    for (auto &[text, inss] : ins_by_text) {
      if (seen.find(text) != seen.end())
        continue;
      static const std::vector<id_t> empty;
      add_group(h, empty, inss);
    }
  }

#ifndef NDEBUG
  // groups should never be empty on both sides.
  for (const auto &g : groups_) {
    assert(g.del_count() + g.ins_count() > 0);
  }
#endif
}

move_registry::id_view
move_registry::delete_ids(const content_group_view &g) const noexcept {
  const id_t *b =
      group_del_ids_.empty() ? nullptr : &group_del_ids_[g.del_begin];
  const id_t *e = group_del_ids_.empty() ? nullptr : &group_del_ids_[g.del_end];
  return id_view{b, e};
}

move_registry::id_view
move_registry::insert_ids(const content_group_view &g) const noexcept {
  const id_t *b =
      group_ins_ids_.empty() ? nullptr : &group_ins_ids_[g.ins_begin];
  const id_t *e = group_ins_ids_.empty() ? nullptr : &group_ins_ids_[g.ins_end];
  return id_view{b, e};
}

std::vector<move_match> move_registry::match_greedy_1_to_1() const {
  std::vector<move_match> out;

  // Upper bound: sum over groups of min(del, ins)
  std::size_t cap = 0;
  for (const auto &g : groups_) {
    cap += std::min(g.del_count(), g.ins_count());
  }
  out.reserve(cap);

  for (const auto &g : groups_) {
    const std::size_t n = std::min(g.del_count(), g.ins_count());
    for (std::size_t k = 0; k < n; ++k) {
      const id_t did =
          group_del_ids_[g.del_begin + static_cast<std::uint32_t>(k)];
      const id_t iid =
          group_ins_ids_[g.ins_begin + static_cast<std::uint32_t>(k)];
      out.push_back(move_match{did, iid});
    }
  }

  return out;
}

std::vector<move_match>
move_registry::enumerate_all_pairs(std::size_t hard_cap) const {
  std::vector<move_match> out;

  for (const auto &g : groups_) {
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
      const id_t did = group_del_ids_[di];
      for (std::uint32_t ii = g.ins_begin; ii < g.ins_end; ++ii) {
        const id_t iid = group_ins_ids_[ii];
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
  os << "  hash buckets: " << by_hash_.size() << "\n";
  os << "  content groups: " << groups_.size() << "\n";

  std::size_t move11 = 0, many = 0, delonly = 0, inonly = 0, copy = 0, amb = 0;
  for (const auto &g : groups_) {
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
  debug(std::cout);

  // FAST baseline: 1-to-1 consumption inside each content group
  auto matches = match_greedy_1_to_1();

  const auto &dels = deletes();
  const auto &inss = inserts();

  std::cout << "\n=== GREEDY MATCHES (DEL -> INS) ===\n";
  for (const auto &m : matches) {
    const auto &d = dels[m.del_id];
    const auto &ins = inss[m.ins_id];

    std::cout << "DEL [" << d.start_idx << "," << d.end_idx << "] "
              << d.filename << "  ->  "
              << "INS [" << ins.start_idx << "," << ins.end_idx << "] "
              << ins.filename << "  hash=" << d.hash
              << "  chars(del)=" << d.full_text.size()
              << "  chars(ins)=" << ins.full_text.size() << "\n";
  }
}

} // namespace srcmove
