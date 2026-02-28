// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file pipeline.hpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */

#ifndef INCLUDED_MOVE_PIPELINE_HPP
#define INCLUDED_MOVE_PIPELINE_HPP

#include <string>

namespace srcmove {

void run_pipeline(const std::string &srcdiff_in_filename,
                  const std::string &srcdiff_out_filename);

} // namespace srcmove

#endif
