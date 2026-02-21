// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file main.cpp
 *
 * @copyright Copyright (C) 2014-2024 SDML (www.srcDiff.org)
 *
 * This file is part of the srcDiff Infrastructure.
 */
#include <cctype>
#include <csetjmp>
#include <cstddef>
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
// #include "xpath_bulder.hpp"

namespace srcmove {

class move_candidate {
public:
  std::string filename; // from unit@filename
  std::string xpath;
  std::string full_name;     // full_name()
  std::size_t sibling_index; // 1-based for siblings with same name under parent
  std::size_t start_index;

  std::size_t add_child_and_get_next_id(std::string full_name) {
    return ++child_counts[full_name];
  }

private:
  std::unordered_map<std::string, std::size_t> child_counts;
};

std::ostream &operator<<(std::ostream &os, const move_candidate &r) {
  return os << "xpath=" << r.xpath;
}

// first pass to get information about the nodes. Return information about
// important nodes
std::vector<move_candidate> collect_move_candidates(srcml_reader &reader) {

  std::string current_file;
  std::vector<move_candidate> out;
  std::vector<move_candidate> tag_stack;

  std::size_t i = 0;
  for (const srcml_node &node : reader) {

    std::cout << node << "\n---------------------------------------------\n";
    // update xpath builder for START first (so current_xpath includes this
    // element)
    for (move_candidate &tag : tag_stack) {
      std::cout << tag << "\n";
    }
    if (node.is_start()) {

      // check if we are at the start of a new page
      if (node.name == "unit") {
        if (const std::string *f = node.get_attribute_value("filename"))
          current_file = *f;
        else
          current_file.clear(); // not all <unit> tags are for files.
      }
      move_candidate current;
      current.full_name = node.full_name();
      current.filename = current_file;
      current.start_index = 0;
      if (tag_stack.empty()) {
        current.xpath = "/" + current.full_name;
        current.sibling_index = 0;
      } else {
        move_candidate &parent = tag_stack.back();
        std::size_t next_sibling_id =
            parent.add_child_and_get_next_id(current.full_name);
        current.xpath = parent.xpath + "/" + current.full_name + "[" +
                        std::to_string(next_sibling_id) + "]";
      }
      tag_stack.push_back(current);
      std::cout << "added to tag_stack: " << node << "\n";
      // todo implement child_counts
    }

    if (node.is_end()) {
      assert((!tag_stack.empty()) && "tag stack is empty on end tag.");
      move_candidate &top = tag_stack.back();
      std::cout << "popping from tag_stack: " << top.full_name << "\n";
      if (top.full_name == "diff:insert" || top.full_name == "diff:delete") {
        out.push_back(top);
        std::cout << "pushed to out: " << node << "\n";
      }
      tag_stack.pop_back();
    }
    ++i;
  }
  return out;
}

void first_pass(srcml_reader &reader) {
  auto move_candidates = collect_move_candidates(reader);
  std::cout << "\n\nmove_candidates in out:\n";
  for (move_candidate &r : move_candidates) {
    std::cout << r << "\n";
  }
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
