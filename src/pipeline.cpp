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
#include "srcml_writer.hpp"
#include "xpath_builder.hpp"

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

struct move_tag {
  std::uint32_t move_id;
};

// Map: start_idx (node index where diff:insert/delete START occurs) -> move tag
using tag_map = std::unordered_map<std::size_t, move_tag>;

static tag_map build_move_tags(const move_registry &mr) {
  tag_map tags;

  std::uint32_t next_move_id = 1;

  for (const auto &g : mr.groups()) {
    if (g.del_count() == 0 || g.ins_count() == 0)
      continue; // only groups with both sides get a move id

    const std::uint32_t move_id = next_move_id++;

    // Apply to all deletes in group
    for (auto did : mr.delete_ids(g)) {
      const auto &d = mr.deletes()[did];
      tags.emplace(d.start_idx, move_tag{move_id});
    }

    // Apply to all inserts in group
    for (auto iid : mr.insert_ids(g)) {
      const auto &ins = mr.inserts()[iid];
      tags.emplace(ins.start_idx, move_tag{move_id});
    }
  }

  return tags;
}

static void write_with_move_annotations(const std::string &in_filename,
                                        const std::string &out_filename,
                                        const tag_map &tags) {
  srcml_reader reader(in_filename);
  srcml_writer writer(out_filename);
  xpath_builder xb;

  std::size_t i = 0;
  for (const srcml_node &node : reader) {
    xb.on_node(node);

    // Patch only START tags of diff:insert / diff:delete when we have a tag.
    if (node.is_start()) {
      const auto fn = node.full_name();
      if (fn == "diff:insert" || fn == "diff:delete") {
        auto it = tags.find(i);
        if (it != tags.end()) {
          srcml_node patched =
              node; // copy so we don't mutate reader-owned node
          patched.set_attribute("move", std::to_string(it->second.move_id));
          patched.set_attribute("xpath", xb.current_xpath());
          writer.write(patched);
          ++i;
          continue;
        }
      }
    }

    writer.write(node);
    ++i;
  }
}

void run_pipeline(const std::string &srcdiff_filename) {
  // first pass
  srcml_reader reader(srcdiff_filename);
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

  // Assign move ids per group and write annotated output
  const auto tags = build_move_tags(mr);

  const std::string out_filename = "diff_new.xml";

  // second pass
  write_with_move_annotations(srcdiff_filename, out_filename, tags);
}

} // namespace srcmove
