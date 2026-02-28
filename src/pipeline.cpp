// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file pipeline.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include <iostream>
#include <string>
#include <vector>

// uncomment to disable assert()
// #define NDEBUG
#include <cassert>

// Use (void) to silence unused warnings.
#define assertm(exp, msg) assert((void(msg), exp))

#include "move_match.hpp"
#include "pipeline.hpp"
#include "srcml_node.hpp"

namespace srcmove {

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

      insert_depth++;
      insert_starts.push_back(i);

      move_candidate x(move_candidate::Kind::insert, i, current_file,
                       reader.get_current_inner_text());
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

      move_candidate x(move_candidate::Kind::del, i, current_file,
                       reader.get_current_inner_text());
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

void first_pass(srcml_reader &reader) {
  auto candidates = collect_regions(reader);

  for (auto &r : candidates) {
    std::cout << (r.kind == move_candidate::Kind::insert ? "INS" : "DEL")
              << " [" << r.start_idx << "," << r.end_idx << "] " << r.filename
              << " hash=" << r.hash << "  raw.ins: '" << r.full_text << "'\n";
  }

  auto matches =
      find_matching_regions_by_hash(candidates, /*confirm_text_equality=*/true);

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
}

} // namespace srcmove
