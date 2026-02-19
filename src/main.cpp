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

struct region {
  enum class kind { insert, del };
  kind k;
  std::size_t start_idx;
  std::size_t end_idx;
  std::string file; // from unit@filename if present
};

std::vector<region> collect_regions(srcml_reader &reader) {
  std::vector<region> out;
  std::string current_file;

  bool in_insert = false;
  bool in_delete = false;
  std::size_t insert_start = 0;
  std::size_t delete_start = 0;

  std::size_t i = 0;
  for (const srcml_node &node : reader) {

    // grab file name when we see <unit ... filename="...">
    if (node.is_start() && node.name == "unit") {
      if (const std::string *f = node.get_attribute_value("filename"))
        current_file = *f;
      else
        current_file.clear();
    }

    // INSERT wrapper
    if (node.is_start() && node.full_name() == "diff:insert") {
      in_insert = true;
      insert_start = i;
    } else if (node.is_end() && node.full_name() == "diff:insert") {
      if (in_insert) {
        region candidate{region::kind::insert, insert_start, i, current_file};
        out.push_back(candidate);
      }
      in_insert = false;
    }

    // DELETE wrapper
    if (node.is_start() && node.full_name() == "diff:delete") {
      in_delete = true;
      delete_start = i;
    } else if (node.is_end() && node.full_name() == "diff:delete") {
      if (in_delete) {
        region candidate{region::kind::del, delete_start, i, current_file};
        out.push_back(candidate);
      }
      in_delete = false;
    }

    ++i;
  }

  return out;
}

void first_pass(srcml_reader &reader) {

  auto regions = collect_regions(reader);
  for (auto &r : regions) {
    std::cout << (r.k == region::kind::insert ? "INS" : "DEL") << " ["
              << r.start_idx << "," << r.end_idx << "] " << r.file << "\n";
  }
  // std::size_t i = 0;
  // for (const srcml_node &node : reader) {
  //   print_node(node, i++);
  // }
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
  } catch (const std::exception &e) {
    std::cerr << "Error: " << e.what() << "\n";
    return 2;
  }

  return 0;
}
