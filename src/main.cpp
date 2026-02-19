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

#include "debug.cpp"
#include "srcml_node.hpp"
#include "srcml_reader.hpp"

void first_pass(srcml_reader &reader) {
  std::size_t i = 0;
  for (const srcml_node &node : reader) {
    print_node(node, i++);
  }
}

int main(int argc, char **argv) {
  if (argc != 2) {
    std::cerr << "usage: " << argv[0] << " <srcdiff.xml>\n";
    return 1;
  }

  std::string filename = argv[1];

  try {
    srcml_reader reader(filename);
    first_pass(reader);

    // for (const srcml_node &node : reader) {
    //   std::cout << node << "\n";
    //
    // // Example: print basic info
    // if (node.is_start()) {
    //   std::cout << "START: " << node.full_name() << "\n";
    // } else if (node.is_end()) {
    //   std::cout << "END:   " << node.full_name() << "\n";
    // } else if (node.is_text() && node.content) {
    //   std::cout << "TEXT:  '" << *node.content << "'\n";
    // }
    // }

  } catch (const std::exception &e) {
    std::cerr << "Error: " << e.what() << "\n";
    return 2;
  }

  return 0;
}
