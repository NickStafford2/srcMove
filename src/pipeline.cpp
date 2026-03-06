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

#include <unordered_map>
#include <utility>
#include <vector>

#include "annotation_writer.hpp"
#include "move_candidate.hpp"
#include "move_region.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_group_builder.hpp"
#include "move_registry/move_registry_debug.hpp"
#include "region_filter.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

static void
add_candidates_grouped_by_file(candidate_registry &registry,
                               std::vector<move_candidate> candidates) {
  std::unordered_map<std::string, std::vector<move_candidate>> by_file;
  by_file.reserve(candidates.size());

  for (auto &candidate : candidates) {
    by_file[candidate.filename].push_back(std::move(candidate));
  }

  for (auto &entry : by_file) {
    registry.add_candidates_for_file(entry.first, std::move(entry.second));
  }
}

void run_pipeline(const std::string &srcdiff_in_filename,
                  const std::string &srcdiff_out_filename) {
  srcml_reader reader(srcdiff_in_filename);

  const auto regions = collect_all_regions(reader);

  const auto filter_options = get_default_filter_options();
  auto candidates = filter_regions_for_registry(regions, filter_options);

  candidate_registry registry;
  registry.reserve(candidates.size());
  add_candidates_grouped_by_file(registry, std::move(candidates));

  const content_groups groups = build_content_groups(registry, true);

  print_greedy_matches(registry, groups, std::cout);

  annotate(regions, registry, groups, srcdiff_in_filename,
           srcdiff_out_filename);
}

} // namespace srcmove
