// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file main.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include <cctype>
#include <cstdint>
#include <iostream>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

// uncomment to disable assert()
// #define NDEBUG
#include <cassert>

// Use (void) to silence unused warnings.
#define assertm(exp, msg) assert((void(msg), exp))

// #include "debug.hpp"
#include "move_candidate.hpp"
#include "srcml_node.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

// 64-bit FNV-1a
inline std::uint64_t fast_hash_raw(std::string_view s) noexcept {
  std::uint64_t hash = 14695981039346656037ull; // offset basis

  for (unsigned char c : s) {
    hash ^= static_cast<std::uint64_t>(c);
    hash *= 1099511628211ull; // FNV prime
  }

  return hash;
}

std::vector<move_candidate> collect_regions(srcml_reader &reader) {
  std::vector<move_candidate> out;
  std::string current_file;

  int insert_depth = 0;
  int delete_depth = 0;

  std::vector<std::size_t> insert_starts;
  std::vector<std::size_t> delete_starts;

  std::size_t i = 0;
  for (const srcml_node &node : reader) {

    if (node.is_start() && node.name == "unit") {
      if (const std::string *f = node.get_attribute_value("filename"))
        current_file = *f;
      else
        current_file.clear();
    }

    // START insert
    if (node.is_start() && node.full_name() == "diff:insert") {
      assert(delete_depth == 0 && "insert inside delete (not handled yet?)");

      std::string raw = reader.get_current_inner_text(); // capture subtree text
      std::uint64_t h = fast_hash_raw(raw);

      insert_depth++;
      insert_starts.push_back(i);

      move_candidate x;
      x.kind = move_candidate::Kind::insert;
      x.start_idx = i;
      x.end_idx = 0;
      x.filename = current_file;
      x.full_text = reader.get_current_inner_text();
      x.hash = fast_hash_raw(x.full_text);

      out.push_back(x);
    }

    // END insert
    if (node.is_end() && node.full_name() == "diff:insert") {
      assert(insert_depth > 0 && "diff:insert end without start");
      insert_depth--;

      // find most recent insert region we opened and close it
      for (auto rit = out.rbegin(); rit != out.rend(); ++rit) {
        if (rit->kind == move_candidate::Kind::insert && rit->end_idx == 0) {
          rit->end_idx = i;
          break;
        }
      }
    }

    // START delete
    if (node.is_start() && node.full_name() == "diff:delete") {
      assert(insert_depth == 0 && "delete inside insert (not handled yet?)");

      delete_depth++;
      delete_starts.push_back(i);

      move_candidate x;
      x.kind = move_candidate::Kind::del;
      x.start_idx = i;
      x.end_idx = 0;
      x.filename = current_file;
      x.full_text = reader.get_current_inner_text();
      x.hash = fast_hash_raw(x.full_text);
      out.push_back(x);
    }

    // END delete
    if (node.is_end() && node.full_name() == "diff:delete") {
      assert(delete_depth > 0 && "diff:delete end without start");
      delete_depth--;

      for (auto rit = out.rbegin(); rit != out.rend(); ++rit) {
        if (rit->kind == move_candidate::Kind::del && rit->end_idx == 0) {
          rit->end_idx = i;
          break;
        }
      }
    }

    ++i;
  }

  assert(insert_depth == 0 && delete_depth == 0);

  // sanity: ensure all regions closed
  for (const auto &r : out) {
    assert(r.end_idx != 0 && "region never closed (end tag missing?)");
  }

  return out;
}

struct match {
  const move_candidate *del;
  const move_candidate *ins;
};

std::vector<match>
find_matching_regions_by_hash(const std::vector<move_candidate> &regions,
                              bool confirm_text_equality = true) {
  // Bucket inserts by hash
  std::unordered_multimap<std::uint64_t, const move_candidate *>
      inserts_by_hash;
  inserts_by_hash.reserve(regions.size());

  std::vector<const move_candidate *> deletes;
  deletes.reserve(regions.size());

  for (const auto &r : regions) {
    if (r.kind == move_candidate::Kind::insert) {
      inserts_by_hash.emplace(r.hash, &r);
    } else {
      deletes.push_back(&r);
    }
  }

  std::vector<match> matches;
  matches.reserve(std::min(deletes.size(), inserts_by_hash.size()));

  // For each delete, find all inserts with same hash
  for (const move_candidate *d : deletes) {
    auto [it, end] = inserts_by_hash.equal_range(d->hash);
    for (; it != end; ++it) {
      const move_candidate *ins = it->second;

      if (confirm_text_equality && d->full_text != ins->full_text)
        continue;

      matches.push_back(match{d, ins});
    }
  }
  return matches;
}

void first_pass(srcml_reader &reader) {
  auto regions = collect_regions(reader);

  // print regions
  for (auto &r : regions) {
    std::cout << (r.kind == move_candidate::Kind::insert ? "INS" : "DEL")
              << " [" << r.start_idx << "," << r.end_idx << "] " << r.filename
              << " hash=" << r.hash << "  raw.ins: '" << r.full_text << "'\n";
  }

  auto matches =
      find_matching_regions_by_hash(regions, /*confirm_text_equality=*/true);

  std::cout << "\n=== HASH MATCHES (DEL -> INS) ===\n";
  for (const auto &m : matches) {
    std::cout << "DEL [" << m.del->start_idx << "," << m.del->end_idx << "] "
              << m.del->filename << "  ->  "
              << "INS [" << m.ins->start_idx << "," << m.ins->end_idx << "] "
              << m.ins->filename << "  hash=" << m.del->hash
              << "  chars(del)=" << m.del->full_text.size()
              << "  chars(ins)=" << m.ins->full_text.size() << "\n  raw.ins: '"
              << m.ins->full_text << "'"
              << "\n  raw.del: '" << m.del->full_text << "'"
              << "\n";
  }
  int i = 1;
}

} // namespace srcmove

int main(int argc, char **argv) {
  if (argc != 2) {
    std::cerr << "usage: " << argv[0] << " <srcdiff.xml>\n";
    return 1;
  }

  std::string filename = argv[1];

  try {
    srcml_reader reader(filename);
    srcmove::first_pass(reader);
  } catch (const std::exception &e) {
    std::cerr << "Error: " << e.what() << "\n";
    return 2;
  }

  return 0;
}
