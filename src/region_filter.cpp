// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file region_filter.cpp
 *
 */
#include <algorithm>
#include <cctype>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "move_candidate.hpp"
#include "parse/canonical_subtree.hpp"
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

static bool is_structural_child_name(std::string_view name) {
  return name == "function" || name == "function_decl" ||
         name == "constructor" || name == "class" || name == "struct" ||
         name == "enum" || name == "namespace" || name == "import";
}

static bool is_statement_name(std::string_view name) {
  return name == "decl_stmt" || name == "expr_stmt" || name == "return" ||
         name == "if_stmt" || name == "for" || name == "while" ||
         name == "do" || name == "switch" || name == "try" || name == "break" ||
         name == "continue" || name == "goto" || name == "throw";
}

static bool is_type2_statement_name(std::string_view name) {
  return name == "decl_stmt" || name == "if_stmt" || name == "for" ||
         name == "while" || name == "do" || name == "switch" || name == "try";
}

static bool is_type2_eligible_name(std::string_view name) {
  return is_structural_child_name(name) || is_type2_statement_name(name);
}

static bool is_preferred_child_candidate_name(std::string_view name) {
  return is_structural_child_name(name) || is_statement_name(name);
}

static std::string
collect_subtree_raw_text(const std::vector<captured_srcml_node> &nodes) {
  std::string out;

  for (const auto &captured : nodes) {
    if (!captured.node.is_text() || !captured.node.content) {
      continue;
    }
    out += *captured.node.content;
  }

  return out;
}

static std::string
collect_subtree_canonical_text(const std::vector<captured_srcml_node> &nodes) {
  std::vector<srcml_node> plain_nodes;
  plain_nodes.reserve(nodes.size());

  for (const auto &captured : nodes) {
    plain_nodes.push_back(captured.node);
  }

  return canonicalize_diff_region_subtree(plain_nodes);
}

struct normalized_subtree {
  std::string canonical;
  std::vector<std::uint64_t> lines;
  std::vector<std::uint64_t> tokens;
};

static normalized_subtree collect_subtree_normalized_text(
    const std::vector<captured_srcml_node> &nodes) {
  std::vector<srcml_node> plain_nodes;
  plain_nodes.reserve(nodes.size());

  for (const auto &captured : nodes) {
    plain_nodes.push_back(captured.node);
  }

  normalized_subtree result;
  canonical_options consistent_options;
  consistent_options.identifiers = identifier_normalization::consistent;
  consistent_options.normalize_literals = true;
  canonicalize_diff_region_subtree(plain_nodes, consistent_options,
                                   &result.lines, &result.tokens);

  canonical_options lexical_options = consistent_options;
  lexical_options.ignore_empty_statements = true;
  lexical_options.include_structure = false;
  result.canonical =
      canonicalize_diff_region_subtree(plain_nodes, lexical_options);
  return result;
}

static bool passes_region_text_filters(const std::string           &raw_text,
                                       const region_filter_options &opt) {
  if (opt.drop_whitespace_only && !any_non_ws(raw_text)) {
    return false;
  }
  if (raw_text.size() < opt.min_chars) {
    return false;
  }
  return true;
}

struct preferred_child_candidates {
  std::vector<move_candidate> candidates;
  std::size_t complete_construct_count = 0;
};

static bool passes_statement_evidence(
    const normalized_subtree &normalized, const region_filter_options &opt) {
  return opt.min_granularity == minimum_move_granularity::fragment ||
         normalized.tokens.size() >= opt.min_statement_tokens;
}

static preferred_child_candidates
extract_preferred_child_candidates(const diff_region           &region,
                                   const region_filter_options &opt) {
  preferred_child_candidates out;

  if (!opt.expand_structural_children || region.captured_nodes.size() < 3) {
    return out;
  }

  std::vector<captured_srcml_node> current;
  current.reserve(64);

  int capturing_depth = 0;

  for (std::size_t i = 1; i + 1 < region.captured_nodes.size(); ++i) {
    const captured_srcml_node &captured = region.captured_nodes[i];
    const srcml_node          &node     = captured.node;

    if (capturing_depth == 0) {
      if (!node.is_start() || !is_preferred_child_candidate_name(node.name)) {
        continue;
      }

      current.clear();
      current.push_back(captured);
      capturing_depth = 1;
      continue;
    }

    current.push_back(captured);

    if (node.is_start()) {
      ++capturing_depth;
    } else if (node.is_end()) {
      --capturing_depth;
    }

    if (capturing_depth != 0) {
      continue;
    }

    std::string raw_text = collect_subtree_raw_text(current);
    if (!passes_region_text_filters(raw_text, opt)) {
      current.clear();
      continue;
    }

    ++out.complete_construct_count;

    std::string canonical_text = collect_subtree_canonical_text(current);
    normalized_subtree normalized =
        collect_subtree_normalized_text(current);
    if (!passes_statement_evidence(normalized, opt)) {
      current.clear();
      continue;
    }
    move_candidate candidate(region.kind, current.front().index,
                             region.filename, std::move(raw_text),
                             std::move(canonical_text),
                             std::move(normalized.canonical),
                             std::move(normalized.lines),
                             std::move(normalized.tokens),
                             is_type2_eligible_name(current.front().node.name));
    candidate.xpath     = current.front().xpath;
    candidate.full_name = current.front().node.full_name();
    candidate.end_idx = current.back().index;
    candidate.role    = move_candidate::Role::structural_child;
    out.candidates.push_back(std::move(candidate));

    current.clear();
  }

  return out;
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

    preferred_child_candidates preferred =
        extract_preferred_child_candidates(r, opt);

    const bool fragment_mode =
        opt.min_granularity == minimum_move_granularity::fragment;
    const bool semantic_wrapper = preferred.complete_construct_count > 0;
    const bool wrapper_has_evidence =
        r.type3_normalized_tokens.size() >= opt.min_statement_tokens;
    if (passes_region_text_filters(r.raw_text, opt) &&
        (fragment_mode || (semantic_wrapper && wrapper_has_evidence))) {
      move_candidate c(r.kind, r.start_idx, r.filename, r.raw_text,
                       r.canonical_text, r.type2_canonical_text,
                       r.type2_normalized_lines, r.type3_normalized_tokens,
                       false);
      c.xpath   = r.start_xpath;
      c.end_idx = r.end_idx; // preserve the true close position
      if (preferred.complete_construct_count == 1) {
        c.role = move_candidate::Role::single_child_wrapper;
      } else if (preferred.complete_construct_count > 1) {
        c.role = move_candidate::Role::multi_child_wrapper;
      } else {
        c.role = move_candidate::Role::diff_wrapper;
      }
      out.push_back(std::move(c));
    }

    out.insert(out.end(),
               std::make_move_iterator(preferred.candidates.begin()),
               std::make_move_iterator(preferred.candidates.end()));
  }

  return out;
}

region_filter_options get_default_filter_options() {
  region_filter_options opt;
  opt.policy                     = region_filter_policy::leaf_only;
  opt.drop_whitespace_only       = true;
  opt.skip_pre_marked            = false;
  opt.expand_structural_children = true;
  opt.min_chars                  = 2;
  return opt;
}

std::vector<move_candidate> collect_regions(srcml_reader &reader) {
  // Default behavior: leaf-only move units, drop whitespace-only.
  auto regions = collect_all_regions(reader);

  region_filter_options opt;
  opt.policy                     = region_filter_policy::leaf_only;
  opt.drop_whitespace_only       = true;
  opt.expand_structural_children = true;
  opt.min_chars                  = 1;

  return filter_regions_for_registry(regions, opt);
}

} // namespace srcmove
