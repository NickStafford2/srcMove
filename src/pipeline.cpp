// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file pipeline.cpp
 *
 * High-level pipeline:
 * - parse srcDiff document into diff regions
 * - filter regions into move candidates
 * - add candidates to registry by actual file unit name
 * - group by content
 * - annotate output xml
 */
#include "pipeline.hpp"

#include <algorithm>
#include <cctype>
#include <set>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>

#include "move_candidate.hpp"
#include "move_sequences.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_group_builder.hpp"
#include "move_registry/content_groups.hpp"
#include "move_registry/move_registry_debug.hpp"
#include "parse/diff_region.hpp"
#include "profile.hpp"
#include "region_filter.hpp"
#include "srcml_reader.hpp"
#include "summary.hpp"
#include "writer/annotation_writer.hpp"

namespace srcmove {

namespace {

// Extension spans arrive in opening-tag order and are nested or disjoint.
// Store one enclosing-span index per record, without copying namespace strings
// into candidates. Lookup costs O(log E + D), where D is extension nesting depth.
class locator_namespace_index {
public:
  explicit locator_namespace_index(const std::vector<xpath_namespace_use> &uses)
      : uses_(uses), parents_(uses.size(), uses.size()) {
    std::vector<std::size_t> open;
    for (std::size_t index = 0; index < uses.size(); ++index) {
      while (!open.empty() && uses[open.back()].end_idx < uses[index].start_idx)
        open.pop_back();
      if (!open.empty()) parents_[index] = open.back();
      open.push_back(index);
    }
  }

  void ancestors(std::size_t position, std::vector<std::size_t> &out) const {
    out.clear();
    const auto after = std::upper_bound(
        uses_.begin(), uses_.end(), position,
        [](std::size_t value, const xpath_namespace_use &use) {
          return value < use.start_idx;
        });
    if (after == uses_.begin()) return;
    for (std::size_t index = static_cast<std::size_t>(after - uses_.begin() - 1);
         index != uses_.size(); index = parents_[index]) {
      if (position <= uses_[index].end_idx) out.push_back(index);
    }
    // Preserve the old outer-to-inner binding order, including benign extras.
    std::reverse(out.begin(), out.end());
  }

private:
  const std::vector<xpath_namespace_use> &uses_;
  std::vector<std::size_t> parents_;
};

void validate_locator_namespaces(
    const std::string &xpath,
    const std::map<std::string, std::string> &bindings) {
  if (xpath.empty() || xpath.front() != '/')
    throw std::runtime_error("invalid_result_locator: expected srcReader locator");
  char quote = 0;
  for (std::size_t index = 0; index < xpath.size();) {
    const char character = xpath[index];
    if (quote != 0) {
      if (character == quote) quote = 0;
      ++index;
      continue;
    }
    if (character == '\'' || character == '"') {
      quote = character;
      ++index;
      continue;
    }
    if (!std::isalpha(static_cast<unsigned char>(character)) && character != '_') {
      ++index;
      continue;
    }
    const std::size_t begin = index++;
    while (index < xpath.size()) {
      const auto next = static_cast<unsigned char>(xpath[index]);
      if (!std::isalnum(next) && next != '_' && next != '-' && next != '.') break;
      ++index;
    }
    if (index < xpath.size() && xpath[index] == ':') {
      const std::string prefix = xpath.substr(begin, index - begin);
      if (bindings.count(prefix) == 0) {
        throw std::runtime_error("unsupported_namespace_context: locator prefix " + prefix);
      }
      ++index;

    }
  }
}

group_kind_counts count_group_kinds(const content_groups &groups) {
  group_kind_counts counts;

  for (const content_group &group : groups.groups()) {
    switch (group.kind) {
    case group_kind::move_1_to_1:
      ++counts.move_1_to_1;
      break;
    case group_kind::moves_many:
      ++counts.moves_many;
      break;
    case group_kind::delete_only:
      ++counts.delete_only;
      break;
    case group_kind::insert_only:
      ++counts.insert_only;
      break;
    case group_kind::copy_or_repeat:
      ++counts.copy_or_repeat;
      break;
    case group_kind::ambiguous:
      ++counts.ambiguous;
      break;
    }
  }

  return counts;
}

content_relationship_counts count_content_relationships(const content_groups &groups) {
  content_relationship_counts counts;

  for (const content_group &group : groups.groups()) {
    if (group.del_count() == 0 || group.ins_count() == 0) {
      continue;
    }

    switch (group.match) {
    case match_kind::type1:
      ++counts.type1;
      break;
    case match_kind::type2:
      ++counts.type2c;
      break;
    case match_kind::type3:
      ++counts.type3;
      break;
    case match_kind::unmatched:
      break;
    }
  }

  return counts;
}

std::size_t count_annotated_regions(const std::vector<move_entry> &moves) {
  std::size_t total = 0;
  for (const move_entry &move : moves) {
    total += move.from_xpaths.size();
    total += move.to_xpaths.size();
  }
  return total;
}

std::size_t estimate_move_pairs(const std::vector<move_entry> &moves) {
  std::size_t total = 0;
  for (const move_entry &move : moves) {
    total += std::min(move.from_xpaths.size(), move.to_xpaths.size());
  }
  return total;
}

std::size_t count_grouped_candidate_ids(const content_groups &groups) {
  std::size_t total = 0;
  for (const content_group &group : groups.groups()) {
    total += group.del_count();
    total += group.ins_count();
  }
  return total;
}

const char *candidate_role_name(move_candidate::Role role) {
  switch (role) {
  case move_candidate::Role::diff_wrapper:
    return "diff_wrapper";
  case move_candidate::Role::single_child_wrapper:
    return "single_child_wrapper";
  case move_candidate::Role::multi_child_wrapper:
    return "multi_child_wrapper";
  case move_candidate::Role::structural_child:
    return "structural_child";
  }
  return "unknown";
}

void collect_candidate_diagnostics(const candidate_registry &registry,
                                   selection_diagnostics &diagnostics) {
  diagnostics.candidates.reserve(registry.active_candidate_count());
  for (std::size_t id = 0; id < registry.total_record_count(); ++id) {
    const candidate_registry::candidate_record &record = registry.record(id);
    if (!record.active) {
      continue;
    }
    const move_candidate &candidate = record.candidate;
    const bool eligible =
        candidate.type2_eligible &&
        candidate.role == move_candidate::Role::structural_child &&
        !candidate.type2_normalized_lines.empty() &&
        !candidate.type3_normalized_tokens.empty();
    diagnostics.candidates.push_back(candidate_diagnostic{
        id,
        candidate.kind == move_candidate::Kind::del ? "delete" : "insert",
        candidate.filename,
        candidate.xpath,
        candidate.full_name,
        candidate_role_name(candidate.role),
        candidate.raw_text,
        eligible,
        candidate.type2_normalized_lines.size(),
        candidate.type3_normalized_tokens.size(),
        candidate.location.revision_file,
    });
  }
}

} // namespace

summary run_pipeline(const std::string &srcdiff_in_filename,
                     const std::string &srcdiff_out_filename,
                     const pipeline_options &options,
                     profile_report    *profile) {
  scoped_profile_timer total_timer(profile, "pipeline.total");

  std::vector<move_candidate> candidates;
  std::vector<std::vector<std::string>> ancestor_summaries;
  std::size_t                 regions_total = 0;
  std::map<std::string, std::string> xpath_namespaces{
      {"src", "http://www.srcML.org/srcML/src"},
      {"diff", "http://www.srcML.org/srcDiff"},
      {"mv", "http://www.srcML.org/srcMove"}};
  std::vector<xpath_namespace_use> xpath_namespace_uses;
  {
    scoped_profile_timer  timer(profile, "pipeline.parse_regions");
    srcml_reader          reader(srcdiff_in_filename);
    region_filter_options filter_options = get_default_filter_options();
    filter_options.min_granularity = options.min_granularity;
    filter_options.collect_type2b_diagnostics = options.diagnostics;
    filter_options.collect_xpath_namespaces = options.results_requested;
    candidate_collection collection =
        collect_candidates_streaming(reader, filter_options, profile);
    candidates = std::move(collection.candidates);
    ancestor_summaries = std::move(collection.ancestor_summaries);
    regions_total = collection.regions_total;
    xpath_namespace_uses = std::move(collection.xpath_namespace_uses);
  }

  candidate_registry registry;
  {
    scoped_profile_timer timer(profile, "pipeline.registry");
    registry.reserve(candidates.size());
    // O(candidates), with expected O(1) hash-bucket insertion per candidate.
    registry.add_candidates_for_file(srcdiff_in_filename,
                                     std::move(candidates),
                                     std::move(ancestor_summaries));
  }

  content_groups groups;
  selection_diagnostics diagnostics;
  if (options.diagnostics) {
    collect_candidate_diagnostics(registry, diagnostics);
  }
  {
    scoped_profile_timer timer(profile, "pipeline.content_groups");
    // potential hook point for new clone detection.
    groups = build_content_groups(
        registry, content_grouping_mode::refined, profile,
        options.diagnostics ? &diagnostics : nullptr);
  }

  if (options.verbose) {
    scoped_profile_timer timer(profile, "pipeline.debug_match_print");
    print_greedy_matches(registry, groups, std::cout);
  }

  if (options.results_requested) {
    scoped_profile_timer timer(profile, "pipeline.locator_namespaces");
    const locator_namespace_index namespace_index(xpath_namespace_uses);
    std::vector<std::size_t> enclosing_namespace_uses;
    // Only the namespace steps of published candidates constrain JSON admission.
    std::set<candidate_id> published;
    if (options.diagnostics) {
      for (candidate_id id = 0; id < registry.total_record_count(); ++id)
        if (registry.is_active(id)) published.insert(id);
    } else {
      for (const auto &group : groups.groups()) {
        if (group.del_count() == 0 || group.ins_count() == 0) continue;
        for (const auto id : groups.delete_ids(group)) published.insert(id);
        for (const auto id : groups.insert_ids(group)) published.insert(id);
      }
    }
    const auto bind_candidate = [&](candidate_id id, bool required) {
      const auto &candidate = registry.candidate(id);
      namespace_index.ancestors(candidate.start_idx, enclosing_namespace_uses);
      for (const auto index : enclosing_namespace_uses) {
        const auto &use = xpath_namespace_uses[index];
        const auto ascii_start = [](unsigned char c) {
          return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
        };
        bool supported = !use.prefix.empty() && ascii_start(use.prefix.front());
        for (const unsigned char c : use.prefix)
          supported = supported && (ascii_start(c) || (c >= '0' && c <= '9') || c == '-' || c == '.');
        if (!supported) {
          if (required) throw std::runtime_error("unsupported_namespace_context: unsupported locator prefix");
          continue;
        }
        const auto [binding, inserted] = xpath_namespaces.emplace(use.prefix, use.uri);
        if (!inserted && binding->second != use.uri && required)
          throw std::runtime_error("unsupported_namespace_context: conflicting locator prefix " + use.prefix);
      }
      if (required) validate_locator_namespaces(candidate.xpath, xpath_namespaces);
    };
    for (const auto id : published) bind_candidate(id, true);
    // Benign extra bindings make standard metadata agree across output modes.
    // Unpublished conflicts cannot veto representable ordinary results.
    for (candidate_id id = 0; id < registry.total_record_count(); ++id)
      if (registry.is_active(id)) bind_candidate(id, false);
  }

  std::vector<move_entry> moves;
  if (options.results_only) {
    scoped_profile_timer timer(profile, "pipeline.results_only");
    moves = collect_move_results(registry, groups, srcdiff_in_filename, profile);
  } else {
    scoped_profile_timer timer(profile, "pipeline.annotation");
    moves = annotate(registry, groups, srcdiff_in_filename,
                     srcdiff_out_filename, profile);
  }

  srcmove::summary result;
  result.xpath_namespaces = std::move(xpath_namespaces);
  result.min_granularity = options.min_granularity == minimum_move_granularity::fragment
                               ? "fragment" : "statement";
  result.registered_candidate_count = registry.total_record_count();
  result.active_candidate_count = registry.active_candidate_count();
  {
    scoped_profile_timer timer(profile, "pipeline.summary");
    result.moves                  = std::move(moves);
    result.move_sequences = build_move_sequences(registry, groups, result.moves);
    result.reported_moves = build_reported_moves(result.moves, result.move_sequences);
    std::unordered_map<std::string, const move_entry *> by_id;
    for (const auto &move : result.moves) by_id.emplace(move.move_id, &move);
    for (const auto &report : result.reported_moves) {
      const auto &relationship = by_id.at(report.member_move_ids.front())->content_relationship;
      if (relationship == "type1") {
        ++result.reported_content_relationships.type1;
      } else if (relationship == "type2c") {
        ++result.reported_content_relationships.type2c;
      } else if (relationship == "type3") {
        ++result.reported_content_relationships.type3;
      }
    }
    result.move_pair_count        = estimate_move_pairs(result.moves);
    result.annotated_region_count = count_annotated_regions(result.moves);
    result.regions_total          = regions_total;
    result.candidates_total       = count_grouped_candidate_ids(groups);
    result.groups_total           = groups.group_count();
    result.group_kinds            = count_group_kinds(groups);
    result.content_relationships            = count_content_relationships(groups);
    result.diagnostics_enabled    = options.diagnostics;
    result.diagnostics            = std::move(diagnostics);
  }

  return result;
}

} // namespace srcmove
