// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file pipeline.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include <cctype>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

// uncomment to disable assert()
// #define NDEBUG
#include <cassert>

#include "move_candidate.hpp"
#include "move_region.hpp"
#include "move_registry.hpp"
#include "pipeline.hpp"
#include "srcml_node.hpp"
#include "srcml_reader.hpp"
#include "srcml_writer.hpp"
#include "xpath_builder.hpp"

namespace srcmove {

move_registry build_registry(std::vector<move_candidate> &candidates) {

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

struct move_tag {
  std::uint32_t move_id;
};

// Map: start_idx (node index where diff:insert/delete START occurs) -> move tag
using tag_map = std::unordered_map<std::size_t, move_tag>;

static std::uint32_t
max_existing_move_id(const std::vector<diff_region> &regions) {
  std::uint32_t mx = 0;
  for (const auto &r : regions) {
    if (r.pre_marked && r.existing_move_id > mx)
      mx = r.existing_move_id;
  }
  return mx;
}

static tag_map build_move_tags(const move_registry &mr,
                               std::uint32_t start_id) {
  tag_map tags;

  std::uint32_t next_move_id = start_id;

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
        // If srcDiff already marked it, never overwrite.
        if (node.get_attribute_value("move")) {
          srcml_node patched =
              node; // copy so we don't mutate reader-owned node
          // still write xpath, even if node already exists.
          patched.set_attribute("xpath", xb.current_xpath());
          writer.write(patched);
          ++i;
          continue;
        }

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

static void debug_print_greedy_matches(const move_registry &mr) {

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
}

void run_pipeline(const std::string &srcdiff_in_filename,
                  const std::string &srcdiff_out_filename) {
  // first pass
  srcml_reader reader(srcdiff_in_filename);
  auto regions = collect_all_regions(reader);

  region_filter_options opt;
  // or leaf_only / all_regions
  opt.policy = region_filter_policy::leaf_only;
  opt.drop_whitespace_only = true;
  opt.skip_pre_marked = true;
  opt.min_chars = 1;

  auto candidates = filter_regions_for_registry(regions, opt);
  move_registry mr = build_registry(candidates);

  debug_print_greedy_matches(mr);

  // Assign move ids per group and write annotated output
  std::uint32_t start_move_id = max_existing_move_id(regions) + 1;
  const auto tags = build_move_tags(mr, start_move_id);

  // second pass
  write_with_move_annotations(srcdiff_in_filename, srcdiff_out_filename, tags);
}

} // namespace srcmove
