// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file main.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include <cctype>
#include <iostream>
#include <string>

#include "pipeline.hpp"

int main(int argc, char **argv) {
  if (argc != 2 && argc != 3) {
    std::cerr << "usage: " << argv[0] << " <srcdiff.xml> [out.xml]\n";
    return 1;
  }

  const std::string in_filename = argv[1];
  const std::string out_filename = (argc == 3) ? argv[2] : "diff_new.xml";

  try {
    srcmove::run_pipeline(in_filename, out_filename);
  } catch (const std::exception &e) {
    std::cerr << "Error: " << e.what() << "\n";
    return 2;
  }

  return 0;
}
