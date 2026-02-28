// SPDX-License-Identifier: GPL-3.0-only
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
  void on_node(const srcml_node &node) {
    if (node.is_start())
      on_start(node);
    else if (node.is_end())
      on_end(node);
  }

  // XPath of the most recently processed START element (i.e., "current
  // element").
  const std::string &current_xpath() const noexcept { return current_xpath_; }

private:
  struct frame {
    std::string name;
    std::size_t index = 1; // 1-based sibling index
    std::unordered_map<std::string, std::size_t> child_counts;
  };

  std::vector<frame> stack_;
  std::string current_xpath_;

  static void append_segment(std::string &out, const std::string &name,
                             std::size_t index) {
    out += "/";
    out += name;
    out += "[";
    out += std::to_string(index);
    out += "]";
  }

  void rebuild_xpath_from_stack() {
    current_xpath_.clear();
    current_xpath_.reserve(stack_.size() * 16);
    for (const auto &f : stack_) {
      append_segment(current_xpath_, f.name, f.index);
    }
    if (current_xpath_.empty())
      current_xpath_ = "/";
  }

  void on_start(const srcml_node &node) {
    const std::string name = node.full_name();

    std::size_t idx = 1;
    if (!stack_.empty()) {
      idx = ++stack_.back().child_counts[name];
    }

    stack_.push_back(frame{name, idx, {}});
    rebuild_xpath_from_stack();
  }

  void on_end(const srcml_node & /*node*/) {
    if (!stack_.empty()) {
      stack_.pop_back();
      rebuild_xpath_from_stack();
    }
  }
};

#endif
