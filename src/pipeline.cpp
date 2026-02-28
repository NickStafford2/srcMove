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

// #include "move_match.hpp"
#include "move_candidate.hpp"
#include "move_registry.hpp"
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

  // ensure all regions closed
  for (const auto &r : out) {
    assert(r.end_idx != 0 && "region never closed (end tag missing?)");
  }

  return out;
}

move_registry build_registry(std::vector<move_candidate> &regions) {

  move_registry mr;
  mr.reserve(/*expected_deletes=*/regions.size(),
             /*expected_inserts=*/regions.size());

  // Feed registry from collected regions
  for (auto &r : regions) {
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

void first_pass(srcml_reader &reader) {
  auto regions = collect_regions(reader);

  move_registry mr = build_registry(regions);

  // Debug/metrics about buckets/groups
  mr.debug(std::cout);

  // FAST baseline: 1-to-1 consumption inside each content group
  auto matches = mr.match_greedy_1_to_1();

  const auto &dels = mr.deletes();
  const auto &inss = mr.inserts();

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
  // move_tag applied to the start tag of diff:insert/diff:delete
  struct move_tag {
    std::uint32_t move_id;
    // xpath will be filled in pass 2 (stream-based)
  };

  std::unordered_map<std::size_t, move_tag> tag_by_start_idx;

  // assign move ids only to groups that have both sides
  std::uint32_t next_move_id = 1;

  for (const auto &g : mr.groups()) {
    if (g.del_count() == 0 || g.ins_count() == 0)
      continue;

    const std::uint32_t move_id = next_move_id++;

    // apply to all deletes in this group
    for (std::uint32_t di = g.del_begin; di < g.del_end; ++di) {
      auto did = mr.group_del_ids_[di]; // private today
      const auto &d = mr.deletes()[did];
      tag_by_start_idx.emplace(d.start_idx, move_tag{move_id});
    }

    // apply to all inserts in this group
    for (std::uint32_t ii = g.ins_begin; ii < g.ins_end; ++ii) {
      auto iid = mr.group_ins_ids_[ii]; // private today
      const auto &ins = mr.inserts()[iid];
      tag_by_start_idx.emplace(ins.start_idx, move_tag{move_id});
    }
  }
}

} // namespace srcmove
