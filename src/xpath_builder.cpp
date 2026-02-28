// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file xpath_builder.cpp
 */
#include "xpath_builder.hpp"
#include <string>
#include <unordered_map>
#include <vector>

#include "srcml_node.hpp"

void xpath_builder::on_node(const srcml_node &node) {
  if (node.is_start())
    on_start(node);
  else if (node.is_end())
    on_end(node);
}

static void append_segment(std::string &out, const std::string &name,
                           std::size_t index) {
  out += "/";
  out += name;
  out += "[";
  out += std::to_string(index);
  out += "]";
}

void xpath_builder::rebuild_xpath_from_stack() {
  current_xpath_.clear();
  current_xpath_.reserve(stack_.size() * 16);
  for (const auto &f : stack_) {
    append_segment(current_xpath_, f.name, f.index);
  }
  if (current_xpath_.empty())
    current_xpath_ = "/";
}

void xpath_builder::on_start(const srcml_node &node) {
  const std::string name = node.full_name();

  std::size_t idx = 1;
  if (!stack_.empty()) {
    idx = ++stack_.back().child_counts[name];
  }

  stack_.push_back(frame{name, idx, {}});
  rebuild_xpath_from_stack();
}

void xpath_builder::on_end(const srcml_node & /*node*/) {
  if (!stack_.empty()) {
    stack_.pop_back();
    rebuild_xpath_from_stack();
  }
}
