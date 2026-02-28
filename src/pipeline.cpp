// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file pipeline.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include <cctype>
#include <string>
#include <vector>

#include "annotation.hpp"
#include "move_region.hpp"
#include "move_registry.hpp"
#include "pipeline.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

void run_pipeline(const std::string &srcdiff_in_filename,
                  const std::string &srcdiff_out_filename) {
  // first pass
  srcml_reader reader(srcdiff_in_filename);
  auto regions = collect_all_regions(reader);
  auto filter_options = get_default_filter_options();
  auto candidates = filter_regions_for_registry(regions, filter_options);
  move_registry mr = build_move_registry(candidates);
  mr.print_greedy_matches();
  annotate(regions, mr, srcdiff_in_filename, srcdiff_out_filename);
}

} // namespace srcmove
