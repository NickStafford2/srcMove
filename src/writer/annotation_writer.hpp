// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file annotation_writer.hpp
 */
#ifndef INCLUDED_MOVE_ANNOTATION_WRITER_HPP
#define INCLUDED_MOVE_ANNOTATION_WRITER_HPP

#include <cctype>
#include <string>
#include <vector>

#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_groups.hpp"
#include "summary.hpp"

namespace srcmove {

class profile_report;

std::vector<move_entry>
collect_move_results(const candidate_registry &registry,
                     const content_groups     &groups,
                     const std::string        &srcdiff_in_filename,
                     profile_report           *profile = nullptr);

std::vector<move_entry> annotate(const candidate_registry &registry,
                                 const content_groups     &groups,
                                 const std::string &srcdiff_in_filename,
                                 const std::string &srcdiff_out_filename,
                                 profile_report    *profile = nullptr);

} // namespace srcmove
#endif
