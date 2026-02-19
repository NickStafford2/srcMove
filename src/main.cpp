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

// uncomment to disable assert()
// #define NDEBUG
#include <cassert>

// Use (void) to silence unused warnings.
#define assertm(exp, msg) assert((void(msg), exp))

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

  int insert_depth = 0;
  int delete_depth = 0;

  std::vector<std::size_t> insert_starts;
  std::vector<std::size_t> delete_starts;

  std::size_t i = 0;
  for (const srcml_node &node : reader) {

    if (node.is_start() && node.name == "unit") {
      if (const std::string *f = node.get_attribute_value("filename"))
        current_file = *f;
      else
        current_file.clear();
    }

    // START insert
    if (node.is_start() && node.full_name() == "diff:insert") {
      // optional constraint for now:
      assert(delete_depth == 0 && "insert inside delete (not handled yet?)");

      insert_depth++;
      insert_starts.push_back(i);
    }

    // END insert
    if (node.is_end() && node.full_name() == "diff:insert") {
      assert(insert_depth > 0 && "diff:insert end without start");
      std::size_t start = insert_starts.back();
      insert_starts.pop_back();
      insert_depth--;

      out.push_back(region{region::kind::insert, start, i, current_file});
    }

    // START delete
    if (node.is_start() && node.full_name() == "diff:delete") {
      assert(insert_depth == 0 && "delete inside insert (not handled yet?)");

      delete_depth++;
      delete_starts.push_back(i);
    }

    // END delete
    if (node.is_end() && node.full_name() == "diff:delete") {
      assert(delete_depth > 0 && "diff:delete end without start");
      std::size_t start = delete_starts.back();
      delete_starts.pop_back();
      delete_depth--;

      out.push_back(region{region::kind::del, start, i, current_file});
    }

    ++i;
  }

  // all regions closed
  assert(insert_depth == 0 && delete_depth == 0);

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
