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
#include "xpath_bulder.hpp"

namespace srcmove {

struct region {
  enum class kind { insert, del };
  kind k;
  std::size_t start_idx;
  std::size_t end_idx;
  std::string file; // from unit@filename

  std::string start_xpath;
  std::string end_xpath;
};

// first pass to get information about the nodes. Return information about
// important nodes
std::vector<region> collect_regions(srcml_reader &reader) {
  std::vector<region> out;
  std::string current_file;

  int insert_depth = 0;
  int delete_depth = 0;

  std::vector<std::size_t> insert_starts;
  std::vector<std::size_t> delete_starts;

  std::vector<std::string> insert_start_xpaths;
  std::vector<std::string> delete_start_xpaths;
  xpath_builder xb;

  std::size_t i = 0;
  for (const srcml_node &node : reader) {

    std::cout << node << "\n---------------------------------------------\n";
    // update xpath builder for START first (so current_xpath includes this
    // element)
    if (node.is_start()) {
      xb.on_node(node);

      // if we are at the start of a new page
      if (node.name == "unit") {
        if (const std::string *f = node.get_attribute_value("filename"))
          current_file = *f;
        else
          current_file.clear(); // not all <unit> tags are for files.
      }

      // START insert
      else if (node.full_name() == "diff:insert") {
        assert(delete_depth == 0 && "insert inside delete (not handled yet?)");

        insert_depth++;
        insert_starts.push_back(i);
        insert_start_xpaths.push_back(xb.current_xpath());
      }

      // START delete
      else if (node.full_name() == "diff:delete") {
        assert(insert_depth == 0 && "delete inside insert (not handled yet?)");

        delete_depth++;
        delete_starts.push_back(i);
        delete_start_xpaths.push_back(xb.current_xpath());
      }
    }

    // For END nodes, snapshot BEFORE popping so xpath still points to the
    // element closing
    if (node.is_end()) {
      if (node.full_name() == "diff:insert") {
        assert(insert_depth > 0 && "diff:insert end without start");

        std::string end_xpath =
            xb.current_xpath(); // currently points to diff:insert[...]

        std::size_t start = insert_starts.back();
        insert_starts.pop_back();
        std::string start_xpath = insert_start_xpaths.back();
        insert_start_xpaths.pop_back();
        insert_depth--;

        out.push_back(region{region::kind::insert, start, i, current_file,
                             start_xpath, end_xpath});
      }

      else if (node.full_name() == "diff:delete") {
        assert(delete_depth > 0 && "diff:delete end without start");

        std::string end_xpath = xb.current_xpath();

        std::size_t start = delete_starts.back();
        delete_starts.pop_back();
        std::string start_xpath = delete_start_xpaths.back();
        delete_start_xpaths.pop_back();
        delete_depth--;

        out.push_back(region{region::kind::del, start, i, current_file,
                             start_xpath, end_xpath});
      }

      // now pop xpath builder on END
      xb.on_node(node);
    }
    ++i;
  }

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

} // namespace srcmove
int main(int argc, char **argv) {
  if (argc != 2) {
    std::cerr << "usage: " << argv[0] << " <srcdiff.xml>\n";
    return 1;
  }

  std::string filename = argv[1];

  try {
    srcml_reader reader(filename);
    srcmove::first_pass(reader);
  } catch (const std::exception &e) {
    std::cerr << "Error: " << e.what() << "\n";
    return 2;
  }

  return 0;
}
