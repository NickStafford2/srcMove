// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file xpath_builder.hpp
 */
#ifndef INCLUDED_XPATH_BUILDER_HPP
#define INCLUDED_XPATH_BUILDER_HPP

#include <string>
#include <unordered_map>
#include <vector>

#include "srcml_node.hpp"

// Builds an XPath-like location for the current element while streaming srcML.
// Path format: /name[index]/child[index]/...
// Uses full_name() (includes prefix like diff:insert).
class xpath_builder {
public:
  void on_node(const srcml_node &node);

  // XPath of the most recently processed START element (i.e., "current
  // element").
  const std::string &current_xpath() const noexcept { return current_xpath_; }

  struct frame {
    std::string name;
    std::size_t index = 1; // 1-based sibling index
    std::unordered_map<std::string, std::size_t> child_counts;
  };

private:
  std::vector<frame> stack_;
  std::string current_xpath_;

  void rebuild_xpath_from_stack();

  void on_start(const srcml_node &node);

  void on_end(const srcml_node & /*node*/);
};

#endif
