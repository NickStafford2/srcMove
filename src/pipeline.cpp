// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file pipeline.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include "pipeline.hpp"
#include "annotation_writer.hpp"
#include "move_region.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_group_builder.hpp"
#include "move_registry/move_registry_debug.hpp"
#include "region_filter.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

void run_pipeline(const std::string &srcdiff_in_filename,
                  const std::string &srcdiff_out_filename) {
  srcml_reader reader(srcdiff_in_filename);

  auto regions = collect_all_regions(reader);
  auto filter_options = get_default_filter_options();
  auto candidates = filter_regions_for_registry(regions, filter_options);
  candidate_registry registry;
  registry.add_candidates_for_file(srcdiff_in_filename, std::move(candidates));
  content_groups groups = build_content_groups(registry, true);
  print_greedy_matches(registry, groups, std::cout);
  annotate(regions, registry, groups, srcdiff_in_filename,
           srcdiff_out_filename);
}

} // namespace srcmove
