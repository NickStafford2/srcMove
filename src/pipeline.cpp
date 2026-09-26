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
#include <utility>
#include <vector>

#include "move_candidate.hpp"
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

match_kind_counts count_match_kinds(const content_groups &groups) {
  match_kind_counts counts;

  for (const content_group &group : groups.groups()) {
    if (group.del_count() == 0 || group.ins_count() == 0) {
      continue;
    }

    switch (group.match) {
    case match_kind::type1:
      ++counts.type1;
      break;
    case match_kind::type2:
      ++counts.type2;
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
  std::size_t                 regions_total = 0;
  {
    scoped_profile_timer  timer(profile, "pipeline.parse_regions");
    srcml_reader          reader(srcdiff_in_filename);
    region_filter_options filter_options = get_default_filter_options();
    filter_options.min_granularity = options.min_granularity;
    candidate_collection collection =
        collect_candidates_streaming(reader, filter_options, profile);
    candidates = std::move(collection.candidates);
    regions_total = collection.regions_total;
  }

  candidate_registry registry;
  {
    scoped_profile_timer timer(profile, "pipeline.registry");
    registry.reserve(candidates.size());
    // O(candidates), with expected O(1) hash-bucket insertion per candidate.
    registry.add_candidates_for_file(srcdiff_in_filename,
                                     std::move(candidates));
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
  {
    scoped_profile_timer timer(profile, "pipeline.summary");
    result.moves                  = std::move(moves);
    result.move_group_count       = result.moves.size();
    result.move_count             = result.move_group_count;
    result.move_pair_count        = estimate_move_pairs(result.moves);
    result.annotated_region_count = count_annotated_regions(result.moves);
    result.annotated_regions      = result.annotated_region_count;
    result.regions_total          = regions_total;
    result.candidates_total       = count_grouped_candidate_ids(groups);
    result.groups_total           = groups.group_count();
    result.group_kinds            = count_group_kinds(groups);
    result.match_kinds            = count_match_kinds(groups);
    result.diagnostics_enabled    = options.diagnostics;
    result.diagnostics            = std::move(diagnostics);
  }

  return result;
}

} // namespace srcmove
