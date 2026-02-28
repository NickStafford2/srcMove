// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file pipeline.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include <cctype>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

// uncomment to disable assert()
// #define NDEBUG
#include <cassert>

#include "annotation.hpp"
#include "move_candidate.hpp"
#include "move_region.hpp"
#include "move_registry.hpp"
#include "pipeline.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

move_registry build_registry(std::vector<move_candidate> &candidates) {

  move_registry mr;
  mr.reserve(/*expected_deletes=*/candidates.size(),
             /*expected_inserts=*/candidates.size());

  // Feed registry from collected regions
  for (auto &r : candidates) {
    if (r.kind == move_candidate::Kind::del) {
      mr.add_delete(std::move(r));
    } else {
      mr.add_insert(std::move(r));
    }
  }

  // Build groups (does equality confirmation + dedupe grouping if enabled)
  mr.finalize(/*confirm_text_equality=*/true);
  return mr;
}

static void debug_print_greedy_matches(const move_registry &mr) {

  // Debug/metrics about buckets/groups
  mr.debug(std::cout);

  // FAST baseline: 1-to-1 consumption inside each content group
  auto matches = mr.match_greedy_1_to_1();

  const auto &dels = mr.deletes();
  const auto &inss = mr.inserts();

  std::cout << "\n=== GREEDY MATCHES (DEL -> INS) ===\n";
  for (const auto &m : matches) {
    const auto &d = dels[m.del_id];
    const auto &ins = inss[m.ins_id];

    std::cout << "DEL [" << d.start_idx << "," << d.end_idx << "] "
              << d.filename << "  ->  "
              << "INS [" << ins.start_idx << "," << ins.end_idx << "] "
              << ins.filename << "  hash=" << d.hash
              << "  chars(del)=" << d.full_text.size()
              << "  chars(ins)=" << ins.full_text.size() << "\n";
  }
}

void run_pipeline(const std::string &srcdiff_in_filename,
                  const std::string &srcdiff_out_filename) {
  // first pass
  srcml_reader reader(srcdiff_in_filename);
  auto regions = collect_all_regions(reader);

  region_filter_options opt;
  // or leaf_only / all_regions
  opt.policy = region_filter_policy::leaf_only;
  opt.drop_whitespace_only = true;
  opt.skip_pre_marked = true;
  opt.min_chars = 1;

  auto candidates = filter_regions_for_registry(regions, opt);
  move_registry mr = build_registry(candidates);

  debug_print_greedy_matches(mr);

  annotate(regions, mr, srcdiff_in_filename, srcdiff_out_filename);
}

} // namespace srcmove
