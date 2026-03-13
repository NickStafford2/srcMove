// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file region_filter.cpp
 *
 */
#include <cctype>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "move_candidate.hpp"
#include "parse/diff_region.hpp"
#include "region_filter.hpp"

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

static std::string trim_ws(std::string s) {
  auto not_space = [](unsigned char ch) { return !std::isspace(ch); };

  auto begin = std::find_if(s.begin(), s.end(), not_space);
  auto end   = std::find_if(s.rbegin(), s.rend(), not_space).base();

  if (begin >= end)
    return "";
  return std::string(begin, end);
}

// Converts selected diff_region -> move_candidate for registry.
// (Registry doesn’t need nesting fields; it just needs text + span + file.)
std::vector<move_candidate>
filter_regions_for_registry(const std::vector<diff_region> &regions,
                            const region_filter_options    &opt) {
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

    if (opt.drop_whitespace_only && !any_non_ws(r.raw_text))
      continue;
    if (r.raw_text.size() < opt.min_chars)
      continue;
    move_candidate c(r.kind, r.start_idx, r.filename, r.raw_text,
                     r.canonical_text);
    c.end_idx = r.end_idx; // preserve the true close position
    out.push_back(std::move(c));
  }

  return out;
}

region_filter_options get_default_filter_options() {
  region_filter_options opt;
  opt.policy               = region_filter_policy::leaf_only;
  opt.drop_whitespace_only = true;
  opt.skip_pre_marked      = true;
  opt.min_chars            = 2;
  return opt;
}

std::vector<move_candidate> collect_regions(srcml_reader &reader) {
  // Default behavior: leaf-only move units, drop whitespace-only.
  auto regions = collect_all_regions(reader);

  region_filter_options opt;
  opt.policy               = region_filter_policy::leaf_only;
  opt.drop_whitespace_only = true;
  opt.min_chars            = 1;

  return filter_regions_for_registry(regions, opt);
}

} // namespace srcmove
