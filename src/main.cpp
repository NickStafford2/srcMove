// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file main.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */

#include <iostream>
#include <string>

#include "srcml_node.hpp"
#include "srcml_reader.hpp"

int main(int argc, char **argv) {
  if (argc != 2) {
    std::cerr << "usage: " << argv[0] << " <srcdiff.xml>\n";
    return 1;
  }

  std::string filename = argv[1];

  try {
    srcml_reader reader(filename);

    for (const srcml_node &node : reader) {

      // Example: print basic info
      if (node.is_start()) {
        std::cout << "START: " << node.full_name() << "\n";
      } else if (node.is_end()) {
        std::cout << "END:   " << node.full_name() << "\n";
      } else if (node.is_text() && node.content) {
        std::cout << "TEXT:  '" << *node.content << "'\n";
      }
    }

  } catch (const std::exception &e) {
    std::cerr << "Error: " << e.what() << "\n";
    return 2;
  }

  return 0;
}
