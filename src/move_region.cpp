// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file move_region.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include <cctype>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

// uncomment to disable assert()
// #define NDEBUG
#include <cassert>

#include "move_candidate.hpp"
#include "move_region.hpp"
#include "pipeline.hpp"
#include "srcml_node.hpp"

namespace srcmove {

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

std::vector<diff_region> collect_all_regions(srcml_reader &reader) {
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

        const std::string *mv = node.get_attribute_value("move");
        if (mv) {
          r.pre_marked = true;
          // best-effort parse (ignore parse errors by leaving 0)
          try {
            r.existing_move_id = static_cast<std::uint32_t>(std::stoul(*mv));
          } catch (...) {
            r.existing_move_id = 0;
          }
        }

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

// Converts selected diff_region -> move_candidate for registry.
// (Registry doesn’t need nesting fields; it just needs text + span + file.)
std::vector<move_candidate>
filter_regions_for_registry(const std::vector<diff_region> &regions,
                            const region_filter_options &opt) {
  std::vector<move_candidate> out;
  out.reserve(regions.size());

  for (const auto &r : regions) {
    if (opt.skip_pre_marked && r.pre_marked)
      continue;

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

std::vector<move_candidate> collect_regions(srcml_reader &reader) {
  // Default behavior: leaf-only move units, drop whitespace-only.
  auto regions = collect_all_regions(reader);

  region_filter_options opt;
  opt.policy = region_filter_policy::leaf_only;
  opt.drop_whitespace_only = true;
  opt.min_chars = 1;

  return filter_regions_for_registry(regions, opt);
}

} // namespace srcmove
