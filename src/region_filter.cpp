// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file region_filter.cpp
 *
 */
#include <algorithm>
#include <cctype>
#include <chrono>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>

#include "move_candidate.hpp"
#include "parse/canonical_subtree.hpp"
#include "parse/diff_region.hpp"
#include "profile.hpp"
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

enum class revision_membership { both, original_only, modified_only };

static std::optional<revision_membership>
revision_membership_from_full_name(std::string_view fn) {
  if (fn == "diff:delete")
    return revision_membership::original_only;
  if (fn == "diff:insert")
    return revision_membership::modified_only;
  if (fn == "diff:common")
    return revision_membership::both;
  return std::nullopt;
}

static revision_membership membership_for(move_candidate::Kind kind) {
  return kind == move_candidate::Kind::del
             ? revision_membership::original_only
             : revision_membership::modified_only;
}

static bool any_non_ws(std::string_view s) {
  for (unsigned char c : s) {
    if (!std::isspace(c))
      return true;
  }
  return false;
}

static bool any_substantive_text(std::string_view s) {
  for (unsigned char c : s) {
    if (std::isalnum(c) || c == '_')
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
collect_subtree_raw_text(const std::vector<captured_srcml_node> &nodes,
                         std::size_t begin, std::size_t end) {
  std::string out;

  for (std::size_t i = begin; i < end; ++i) {
    const auto &captured = nodes[i];
    if (!captured.node.is_text() || !captured.node.content) {
      continue;
    }
    out += *captured.node.content;
  }

  return out;
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
    const std::vector<std::uint64_t> &normalized_tokens,
    const region_filter_options      &opt) {
  return opt.min_granularity == minimum_move_granularity::fragment ||
         normalized_tokens.size() >= opt.min_statement_tokens;
}

static preferred_child_candidates
extract_preferred_child_candidates(const diff_region           &region,
                                   const region_filter_options &opt) {
  preferred_child_candidates out;

  if (!opt.expand_structural_children || region.captured_nodes.size() < 3) {
    return out;
  }

  std::size_t candidate_begin = kNoParent;
  int         capturing_depth = 0;

  for (std::size_t i = 1; i + 1 < region.captured_nodes.size(); ++i) {
    const captured_srcml_node &captured = region.captured_nodes[i];
    const srcml_node          &node     = captured.node;

    if (capturing_depth == 0) {
      if (!node.is_start() || !is_preferred_child_candidate_name(node.name)) {
        continue;
      }

      candidate_begin = i;
      capturing_depth = 1;
      continue;
    }

    if (node.is_start()) {
      ++capturing_depth;
    } else if (node.is_end()) {
      --capturing_depth;
    }

    if (capturing_depth != 0) {
      continue;
    }

    const std::size_t candidate_end = i + 1;
    std::string raw_text = collect_subtree_raw_text(
        region.captured_nodes, candidate_begin, candidate_end);
    if (!passes_region_text_filters(raw_text, opt)) {
      candidate_begin = kNoParent;
      continue;
    }

    ++out.complete_construct_count;

    canonical_forms forms = canonicalize_diff_region_forms(
        region.captured_nodes, candidate_begin, candidate_end);
    if (!passes_statement_evidence(forms.normalized_tokens, opt)) {
      candidate_begin = kNoParent;
      continue;
    }
    const captured_srcml_node &first = region.captured_nodes[candidate_begin];
    const captured_srcml_node &last  = region.captured_nodes[candidate_end - 1];
    move_candidate candidate(region.kind, first.index,
                             region.filename, std::move(raw_text),
                             std::move(forms.exact),
                             std::move(forms.type2_canonical),
                             std::move(forms.normalized_lines),
                             std::move(forms.normalized_tokens),
                             is_type2_eligible_name(first.node.name));
    candidate.xpath     = first.xpath;
    candidate.full_name = first.node.full_name();
    candidate.end_idx   = last.index;
    candidate.role      = move_candidate::Role::structural_child;
    out.candidates.push_back(std::move(candidate));

    candidate_begin = kNoParent;
  }

  return out;
}

namespace {

using stream_clock = std::chrono::steady_clock;

// The pipeline path below builds candidates while srcReader advances. It keeps
// only canonicalization state and completed candidates; the region-based path
// remains available for focused tests and callers that need captured XML.

struct streamed_child {
  canonical_forms_builder forms;
  std::string              raw_text;
  std::string              xpath;
  std::string              full_name;
  std::size_t              start_idx      = 0;
  int                      depth          = 0;
  bool                     type2_eligible = false;
  std::size_t substantive_same_side = 0;
  std::size_t substantive_common = 0;
  std::size_t substantive_opposite = 0;
};

struct streamed_region {
  move_candidate::Kind kind;
  std::string          filename;
  std::size_t          start_idx = 0;
  std::size_t          parent_id = kNoParent;
  std::string          start_xpath;
  std::string          raw_text;
  std::optional<canonical_forms_builder> forms;
  std::vector<streamed_child>             children;
  std::vector<move_candidate>             preferred_candidates;
  std::size_t complete_construct_count = 0;
  std::size_t substantive_same_side     = 0;
  std::size_t substantive_common        = 0;
  std::size_t substantive_opposite      = 0;
  bool        has_diff_child           = false;
  bool        pre_marked               = false;
};

struct streaming_profile_stats {
  std::uint64_t reader_events          = 0;
  std::uint64_t start_events           = 0;
  std::uint64_t end_events             = 0;
  std::uint64_t text_events            = 0;
  std::uint64_t other_events           = 0;
  std::uint64_t regions_opened         = 0;
  std::uint64_t region_node_visits     = 0;
  std::uint64_t child_node_visits      = 0;
  std::uint64_t xpath_calls            = 0;
  std::uint64_t max_diff_depth         = 0;
  std::uint64_t nested_same_side       = 0;
  std::uint64_t nested_cross_side      = 0;
  std::uint64_t leaf_parents_abandoned = 0;
  std::uint64_t common_regions_opened  = 0;
  std::uint64_t common_inside_diff     = 0;
  double        xpath_ms           = 0.0;
};

std::string streaming_xpath(srcml_reader &reader,
                            streaming_profile_stats *stats) {
  if (stats == nullptr) {
    return reader.get_current_xpath();
  }
  const auto start = stream_clock::now();
  std::string xpath = reader.get_current_xpath();
  ++stats->xpath_calls;
  stats->xpath_ms +=
      std::chrono::duration<double, std::milli>(stream_clock::now() - start)
          .count();
  return xpath;
}

void record_stream_event(const srcml_node &node,
                         streaming_profile_stats *stats) {
  if (stats == nullptr) {
    return;
  }
  ++stats->reader_events;
  if (node.is_start()) {
    ++stats->start_events;
  } else if (node.is_end()) {
    ++stats->end_events;
  } else if (node.is_text()) {
    ++stats->text_events;
  } else {
    ++stats->other_events;
  }
}

bool keep_streamed_region(const streamed_region       &region,
                          const region_filter_options &opt) {
  if (opt.skip_pre_marked && region.pre_marked) {
    return false;
  }
  switch (opt.policy) {
  case region_filter_policy::revision_aware:
    return region.substantive_same_side != 0 &&
           region.substantive_common == 0 &&
           region.substantive_opposite == 0;
  case region_filter_policy::leaf_only:
    return !region.has_diff_child;
  case region_filter_policy::top_level_only:
    return region.parent_id == kNoParent;
  case region_filter_policy::all_regions:
    return true;
  }
  return false;
}

void finish_streamed_child(streamed_region             &region,
                           streamed_child                child,
                           std::size_t                   end_idx,
                           const region_filter_options &opt) {
  if (child.substantive_same_side == 0 || child.substantive_common != 0 ||
      child.substantive_opposite != 0) {
    return;
  }
  if (!passes_region_text_filters(child.raw_text, opt)) {
    return;
  }
  ++region.complete_construct_count;

  canonical_forms forms = child.forms.finish();
  if (!passes_statement_evidence(forms.normalized_tokens, opt)) {
    return;
  }

  move_candidate candidate(
      region.kind, child.start_idx, region.filename, std::move(child.raw_text),
      std::move(forms.exact), std::move(forms.type2_canonical),
      std::move(forms.normalized_lines), std::move(forms.normalized_tokens),
      child.type2_eligible);
  candidate.xpath     = std::move(child.xpath);
  candidate.full_name = std::move(child.full_name);
  candidate.end_idx   = end_idx;
  candidate.role      = move_candidate::Role::structural_child;
  region.preferred_candidates.push_back(std::move(candidate));
}

void consume_streamed_children(
    streamed_region &region, const srcml_node &node, srcml_reader &reader,
    std::size_t node_index, revision_membership effective,
    bool substantive, const region_filter_options &opt,
    streaming_profile_stats *stats) {
  if (!opt.expand_structural_children) {
    return;
  }

  for (streamed_child &child : region.children) {
    child.forms.consume(node);
    if (node.is_text() && node.content) {
      child.raw_text += *node.content;
    }
    if (substantive) {
      if (effective == membership_for(region.kind)) {
        ++child.substantive_same_side;
      } else if (effective == revision_membership::both) {
        ++child.substantive_common;
      } else {
        ++child.substantive_opposite;
      }
    }
    if (node.is_start()) {
      ++child.depth;
    } else if (node.is_end()) {
      --child.depth;
    }
    if (stats != nullptr) {
      ++stats->child_node_visits;
    }
  }

  if (node.is_start() && is_preferred_child_candidate_name(node.name)) {
    streamed_child child;
    child.xpath          = streaming_xpath(reader, stats);
    child.full_name      = node.full_name();
    child.start_idx      = node_index;
    child.depth          = 1;
    child.type2_eligible = is_type2_eligible_name(node.name);
    child.forms.consume(node);
    region.children.push_back(std::move(child));
    if (stats != nullptr) {
      ++stats->child_node_visits;
    }
  }

  while (!region.children.empty() && region.children.back().depth == 0) {
    streamed_child child = std::move(region.children.back());
    region.children.pop_back();
    finish_streamed_child(region, std::move(child), node_index, opt);
  }
}

void finish_streamed_region(
    streamed_region &region, std::size_t region_id, std::size_t end_idx,
    const region_filter_options &opt,
    std::vector<std::vector<move_candidate>> &candidate_sets) {
  if (!region.children.empty()) {
    throw std::runtime_error("diff region ended inside a candidate subtree");
  }
  if (!region.forms) {
    throw std::runtime_error("selected diff region has no canonical state");
  }

  canonical_forms forms = region.forms->finish();
  std::vector<move_candidate> &out = candidate_sets.at(region_id);

  if (!keep_streamed_region(region, opt)) {
    out.insert(out.end(),
               std::make_move_iterator(region.preferred_candidates.begin()),
               std::make_move_iterator(region.preferred_candidates.end()));
    return;
  }

  const bool fragment_mode =
      opt.min_granularity == minimum_move_granularity::fragment;
  const bool semantic_wrapper = region.complete_construct_count > 0;
  const bool wrapper_has_evidence =
      forms.normalized_tokens.size() >= opt.min_statement_tokens;
  if (passes_region_text_filters(region.raw_text, opt) &&
      (fragment_mode || (semantic_wrapper && wrapper_has_evidence))) {
    move_candidate candidate(
        region.kind, region.start_idx, region.filename, region.raw_text,
        forms.exact, forms.type2_canonical, forms.normalized_lines,
        forms.normalized_tokens, false);
    candidate.xpath   = region.start_xpath;
    candidate.end_idx = end_idx;
    if (region.complete_construct_count == 1) {
      candidate.role = move_candidate::Role::single_child_wrapper;
    } else if (region.complete_construct_count > 1) {
      candidate.role = move_candidate::Role::multi_child_wrapper;
    } else {
      candidate.role = move_candidate::Role::diff_wrapper;
    }
    out.push_back(std::move(candidate));
  }

  out.insert(out.end(),
             std::make_move_iterator(region.preferred_candidates.begin()),
             std::make_move_iterator(region.preferred_candidates.end()));
}

} // namespace

candidate_collection
collect_candidates_streaming(srcml_reader                &reader,
                             const region_filter_options &opt,
                             profile_report              *profile) {
  streaming_profile_stats profile_storage;
  streaming_profile_stats *stats =
      profile == nullptr ? nullptr : &profile_storage;

  std::vector<streamed_region> regions;
  std::vector<std::size_t> open_regions;
  std::vector<revision_membership> revision_states;
  std::size_t ignored_evidence_depth = 0;
  std::vector<std::vector<move_candidate>> candidate_sets;
  regions.reserve(256);
  open_regions.reserve(32);
  revision_states.reserve(32);
  candidate_sets.reserve(256);

  auto open_region = [&](move_candidate::Kind kind, const srcml_node &node,
                         const std::string &filename,
                         std::size_t node_index) {
    const std::size_t parent_id =
        open_regions.empty() ? kNoParent : open_regions.back();
    if (parent_id != kNoParent) {
      streamed_region &parent = regions[parent_id];
      parent.has_diff_child = true;
      if (stats != nullptr) {
        if (parent.kind == kind) {
          ++stats->nested_same_side;
        } else {
          ++stats->nested_cross_side;
        }
      }
      if (opt.policy == region_filter_policy::leaf_only) {
        if (stats != nullptr) {
          ++stats->leaf_parents_abandoned;
        }
        parent.forms.reset();
        parent.children.clear();
        parent.preferred_candidates.clear();
        parent.raw_text.clear();
      }
    }

    streamed_region region{kind};
    region.filename    = filename;
    region.start_idx   = node_index;
    region.parent_id   = parent_id;
    region.start_xpath = streaming_xpath(reader, stats);
    region.forms.emplace();
    region.pre_marked  = node.get_attribute_value("move") != nullptr;

    regions.push_back(std::move(region));
    candidate_sets.emplace_back();
    open_regions.push_back(regions.size() - 1);
    if (stats != nullptr) {
      ++stats->regions_opened;
      stats->max_diff_depth =
          std::max<std::uint64_t>(stats->max_diff_depth, open_regions.size());
    }
  };

  auto consume_node = [&](const srcml_node &node, const std::string &filename,
                          std::size_t node_index) {
    const std::string full_name = node.full_name();
    const auto        kind      = diff_kind_from_full_name(full_name);
    const auto state = revision_membership_from_full_name(full_name);
    const bool ignored_evidence_container =
        node.name == "comment" || full_name == "diff:ws";
    if (node.is_start() && ignored_evidence_container) {
      ++ignored_evidence_depth;
    }
    if (stats != nullptr && node.is_start() && full_name == "diff:common") {
      ++stats->common_regions_opened;
      if (!open_regions.empty()) {
        ++stats->common_inside_diff;
      }
    }
    if (node.is_start() && kind) {
      open_region(*kind, node, filename, node_index);
    }
    if (node.is_start() && state) {
      revision_states.push_back(*state);
    }

    std::size_t closing_id = kNoParent;
    if (node.is_end() && kind) {
      if (open_regions.empty() || regions[open_regions.back()].kind != *kind) {
        throw std::runtime_error("mismatched diff nesting");
      }
      closing_id = open_regions.back();
    }

    if (node.is_end() && state &&
        (revision_states.empty() || revision_states.back() != *state)) {
      throw std::runtime_error("mismatched srcDiff revision-state nesting");
    }

    const bool substantive =
        ignored_evidence_depth == 0 && node.is_text() && node.content &&
        any_substantive_text(*node.content);
    if (substantive && !open_regions.empty()) {
      const revision_membership effective =
          revision_states.empty() ? revision_membership::both
                                  : revision_states.back();
      for (std::size_t region_id : open_regions) {
        streamed_region &region = regions[region_id];
        if (effective == membership_for(region.kind)) {
          ++region.substantive_same_side;
        } else if (effective == revision_membership::both) {
          ++region.substantive_common;
        } else {
          ++region.substantive_opposite;
        }
      }
    }

    for (std::size_t region_id : open_regions) {
      streamed_region &region = regions[region_id];
      if (!region.forms) {
        continue;
      }
      region.forms->consume(node);
      if (node.is_text() && node.content) {
        region.raw_text += *node.content;
      }
      if (stats != nullptr) {
        ++stats->region_node_visits;
      }
      const revision_membership effective =
          revision_states.empty() ? revision_membership::both
                                  : revision_states.back();
      consume_streamed_children(region, node, reader, node_index, effective,
                                substantive, opt, stats);
    }

    if (closing_id != kNoParent) {
      streamed_region &region = regions[closing_id];
      finish_streamed_region(region, closing_id, node_index, opt,
                             candidate_sets);
      region.forms.reset();
      region.children.clear();
      region.raw_text.clear();
      region.start_xpath.clear();
      region.filename.clear();
      region.preferred_candidates.clear();
      open_regions.pop_back();
    }
    if (node.is_end() && state) {
      revision_states.pop_back();
    }
    if (node.is_end() && ignored_evidence_container) {
      if (ignored_evidence_depth == 0) {
        throw std::runtime_error("mismatched ignored evidence container");
      }
      --ignored_evidence_depth;
    }
  };

  auto it  = reader.begin();
  auto end = reader.end();
  if (!(it != end) || !it->is_start() || it->name != "unit") {
    throw std::runtime_error("expected root <unit> as first node");
  }

  std::size_t node_index = 0;
  record_stream_event(*it, stats);
  const std::string *root_filename = it->get_attribute_value("filename");
  if (root_filename != nullptr && root_filename->empty()) {
    throw std::runtime_error("root single-file unit: expected unit@filename");
  }
  const bool archive = root_filename == nullptr;
  bool       in_file      = !archive;
  bool       document_done = false;
  std::string filename = archive ? std::string() : *root_filename;
  ++it;
  ++node_index;

  while (it != end) {
    const srcml_node &node = *it;
    record_stream_event(node, stats);

    if (document_done) {
      ++it;
      ++node_index;
      continue;
    }

    if (archive && !in_file) {
      if (node.is_start()) {
        if (node.name != "unit") {
          throw std::runtime_error("unexpected start tag at archive level: " +
                                   node.full_name());
        }
        const std::string *value = node.get_attribute_value("filename");
        if (value == nullptr || value->empty()) {
          throw std::runtime_error(
              "archive child file unit: expected unit@filename");
        }
        filename = *value;
        in_file = true;
      } else if (node.is_end()) {
        if (node.name != "unit") {
          throw std::runtime_error("unexpected end tag at archive level: " +
                                   node.full_name());
        }
        document_done = true;
      }
      ++it;
      ++node_index;
      continue;
    }

    if (node.is_start() && node.name == "unit") {
      throw std::runtime_error("unexpected nested <unit> inside file unit: " +
                               filename);
    }
    if (node.is_end() && node.name == "unit") {
      if (!open_regions.empty()) {
        throw std::runtime_error(
            "file unit ended before all diff regions were closed: " +
            filename);
      }
      if (!revision_states.empty()) {
        throw std::runtime_error(
            "file unit ended before all srcDiff states were closed: " +
            filename);
      }
      in_file = false;
      filename.clear();
      if (!archive) {
        document_done = true;
      }
      ++it;
      ++node_index;
      continue;
    }

    consume_node(node, filename, node_index);
    ++it;
    ++node_index;
  }

  if (!open_regions.empty()) {
    throw std::runtime_error("unexpected EOF while reading diff region");
  }
  if (!revision_states.empty()) {
    throw std::runtime_error("unexpected EOF while reading srcDiff state");
  }
  if (!document_done) {
    throw std::runtime_error("unexpected EOF while reading srcDiff document");
  }

  candidate_collection result;
  result.regions_total = regions.size();
  std::unordered_set<std::string> seen_candidates;
  for (auto &set : candidate_sets) {
    for (move_candidate &candidate : set) {
      std::string key;
      key.reserve(candidate.filename.size() + candidate.full_name.size() +
                  candidate.canonical_text.size() + 64);
      key.push_back(candidate.kind == move_candidate::Kind::del ? 'd' : 'i');
      key.push_back('\0');
      key += candidate.filename;
      key.push_back('\0');
      key += std::to_string(candidate.start_idx);
      key.push_back(':');
      key += std::to_string(candidate.end_idx);
      key.push_back(':');
      key += std::to_string(static_cast<int>(candidate.role));
      key.push_back('\0');
      key += candidate.full_name;
      key.push_back('\0');
      key += candidate.canonical_text;
      if (seen_candidates.insert(std::move(key)).second) {
        result.candidates.push_back(std::move(candidate));
      }
    }
  }

  if (profile != nullptr) {
    profile->add_ms("parse.xpath", profile_storage.xpath_ms);
    profile->add_counter("parse.reader_events", profile_storage.reader_events);
    profile->add_counter("parse.start_events", profile_storage.start_events);
    profile->add_counter("parse.end_events", profile_storage.end_events);
    profile->add_counter("parse.text_events", profile_storage.text_events);
    profile->add_counter("parse.other_events", profile_storage.other_events);
    profile->add_counter("parse.diff_regions_opened",
                         profile_storage.regions_opened);
    profile->add_counter("parse.max_diff_depth",
                         profile_storage.max_diff_depth);
    profile->add_counter("parse.nested_same_side_regions",
                         profile_storage.nested_same_side);
    profile->add_counter("parse.nested_cross_side_regions",
                         profile_storage.nested_cross_side);
    profile->add_counter("parse.leaf_only_parents_abandoned",
                         profile_storage.leaf_parents_abandoned);
    profile->add_counter("parse.common_regions_opened",
                         profile_storage.common_regions_opened);
    profile->add_counter("parse.common_regions_inside_diff",
                         profile_storage.common_inside_diff);
    profile->add_counter("parse.xpath_calls", profile_storage.xpath_calls);
    profile->add_counter("parse.streaming_region_node_visits",
                         profile_storage.region_node_visits);
    profile->add_counter("parse.streaming_child_node_visits",
                         profile_storage.child_node_visits);
    profile->add_counter("parse.streaming_candidates",
                         result.candidates.size());
    profile->add_counter("parse.captured_node_insertions", 0);
    profile->add_counter("parse.duplicate_capture_insertions", 0);
  }
  return result;
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
    case region_filter_policy::revision_aware:
      // The captured-region compatibility path predates revision ownership.
      // Conservatively retain its old leaf behavior until it carries the same
      // state summary as the production streaming path.
      keep = !r.has_diff_child;
      break;
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
  opt.policy                     = region_filter_policy::revision_aware;
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
