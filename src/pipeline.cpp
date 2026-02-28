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
#include <optional>
#include <string>
#include <string_view>
#include <utility>
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

// -----------------------------------------
// 1) Region model collected from srcDiff
// -----------------------------------------
struct diff_region {
  move_candidate::Kind kind;
  std::string filename;

  std::size_t start_idx = 0; // node stream index of START tag
  std::size_t end_idx = 0;   // node stream index of END tag

  std::string full_text;  // reader.get_current_inner_text() at START
  std::uint64_t hash = 0; // hash(full_text) (optional for filtering)

  // nesting metadata
  std::size_t parent_id = static_cast<std::size_t>(-1);
  std::uint32_t depth = 0;
  bool has_diff_child = false;
};

static constexpr std::size_t kNoParent = static_cast<std::size_t>(-1);

static std::optional<move_candidate::Kind>
diff_kind_from_full_name(std::string_view fn) {
  if (fn == "diff:insert")
    return move_candidate::Kind::insert;
  if (fn == "diff:delete")
    return move_candidate::Kind::del;
  return std::nullopt;
}

static bool any_non_ws(std::string_view s) {
  for (unsigned char c : s) {
    if (!std::isspace(c))
      return true;
  }
  return false;
}

// -----------------------------------------
// 2) Collect ALL diff regions (nested-safe)
// -----------------------------------------
static std::vector<diff_region> collect_all_regions(srcml_reader &reader) {
  std::vector<diff_region> regions;
  regions.reserve(256);

  std::string current_file;

  // Stack of open region ids (index into `regions`).
  std::vector<std::size_t> open;
  open.reserve(64);

  std::size_t node_index = 0;
  for (const srcml_node &node : reader) {

    // Track unit filename as you did before.
    if (node.is_start() && node.name == "unit") {
      if (const std::string *f = node.get_attribute_value("filename"))
        current_file = *f;
      else
        current_file.clear();
    }

    const std::string fn = node.full_name();

    // START diff region
    if (node.is_start()) {
      if (auto k = diff_kind_from_full_name(fn)) {
        const std::size_t parent = open.empty() ? kNoParent : open.back();
        const std::uint32_t depth = static_cast<std::uint32_t>(open.size());

        if (parent != kNoParent) {
          regions[parent].has_diff_child = true;
        }

        diff_region r;
        r.kind = *k;
        r.filename = current_file;
        r.start_idx = node_index;
        r.end_idx = 0;
        r.full_text = reader.get_current_inner_text();
        r.hash = move_candidate::fast_hash_raw(r.full_text);
        r.parent_id = parent;
        r.depth = depth;

        regions.push_back(std::move(r));
        open.push_back(regions.size() - 1);
      }
    }

    // END diff region
    if (node.is_end()) {
      if (auto k = diff_kind_from_full_name(fn)) {
        assert(!open.empty() && "diff end without start");
        const std::size_t rid = open.back();
        open.pop_back();

        // Validate nesting structure: end tag should match the last opened
        // kind.
        assert(regions[rid].kind == *k && "diff nesting mismatch");
        assert(regions[rid].end_idx == 0 && "region already closed");
        regions[rid].end_idx = node_index;
      }
    }

    ++node_index;
  }

  assert(open.empty() && "diff region never closed (missing end tag?)");

#ifndef NDEBUG
  for (const auto &r : regions) {
    assert(r.end_idx != 0 && "diff region never closed (missing end tag?)");
  }
#endif

  return regions;
}

// -----------------------------------------
// 3) Filtering policy (choose move units)
// -----------------------------------------
enum class region_filter_policy {
  leaf_only,      // regions with no diff children (usually best for moves)
  top_level_only, // parent == none (outer wrappers / hunks)
  all_regions     // everything
};

struct region_filter_options {
  region_filter_policy policy = region_filter_policy::leaf_only;

  // Common practical filters:
  bool drop_whitespace_only = true;
  std::size_t min_chars = 1; // after whitespace-only check (still raw chars)
};

// Converts selected diff_region -> move_candidate for registry.
// (Registry doesn’t need nesting fields; it just needs text + span + file.)
static std::vector<move_candidate>
filter_regions_for_registry(const std::vector<diff_region> &regions,
                            const region_filter_options &opt) {
  std::vector<move_candidate> out;
  out.reserve(regions.size());

  for (const auto &r : regions) {
    bool keep = false;
    switch (opt.policy) {
    case region_filter_policy::leaf_only:
      keep = !r.has_diff_child;
      break;
    case region_filter_policy::top_level_only:
      keep = (r.parent_id == kNoParent);
      break;
    case region_filter_policy::all_regions:
      keep = true;
      break;
    }

    if (!keep)
      continue;

    if (opt.drop_whitespace_only && !any_non_ws(r.full_text))
      continue;
    if (r.full_text.size() < opt.min_chars)
      continue;

    move_candidate c(r.kind, r.start_idx, r.filename, r.full_text);
    c.end_idx = r.end_idx; // preserve the true close position
    out.push_back(std::move(c));
  }

  return out;
}

// -----------------------------------------
// 4) Public entry: your existing signature
// -----------------------------------------
std::vector<move_candidate> collect_regions(srcml_reader &reader) {
  // Default behavior: leaf-only move units, drop whitespace-only.
  auto regions = collect_all_regions(reader);

  region_filter_options opt;
  opt.policy = region_filter_policy::leaf_only;
  opt.drop_whitespace_only = true;
  opt.min_chars = 1;

  return filter_regions_for_registry(regions, opt);
}

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
  auto all = collect_all_regions(reader);

  region_filter_options opt;
  // or leaf_only / all_regions
  opt.policy = region_filter_policy::leaf_only;
  opt.drop_whitespace_only = true;
  opt.min_chars = 1;

  auto candidates = filter_regions_for_registry(all, opt);
  move_registry mr = build_registry(candidates);

  debug_print_greedy_matches(mr);

  // Assign move ids per group and write annotated output
  const auto tags = build_move_tags(mr);

  // second pass
  write_with_move_annotations(srcdiff_in_filename, srcdiff_out_filename, tags);
}

} // namespace srcmove
