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

#include <utility>
#include <vector>

#include "move_candidate.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_group_builder.hpp"
#include "move_registry/content_groups.hpp"
#include "move_registry/move_registry_debug.hpp"
#include "parse/diff_region.hpp"
#include "region_filter.hpp"
#include "srcml_reader.hpp"
#include "summary.hpp"
#include "writer/annotation_writer.hpp"

namespace srcmove {

summary run_pipeline(const std::string &srcdiff_in_filename,
                     const std::string &srcdiff_out_filename) {
  srcml_reader reader(srcdiff_in_filename);

  const std::vector<diff_region> regions        = collect_all_regions(reader);
  const region_filter_options    filter_options = get_default_filter_options();
  std::vector<move_candidate>    candidates =
      filter_regions_for_registry(regions, filter_options);

  candidate_registry registry;
  registry.reserve(candidates.size());
  registry.add_candidates_for_file(srcdiff_in_filename, std::move(candidates));
  const content_groups groups = build_content_groups(registry, true);

  print_greedy_matches(registry, groups, std::cout);

  std::vector<move_entry> moves = annotate(
      regions, registry, groups, srcdiff_in_filename, srcdiff_out_filename);

  srcmove::summary result;
  result.moves             = std::move(moves);
  result.move_count        = result.moves.size();
  result.annotated_regions = result.move_count * 2;
  result.regions_total     = regions.size();
  result.candidates_total  = registry.active_candidate_count();
  result.groups_total      = groups.group_count();
  return result;
}

} // namespace srcmove
