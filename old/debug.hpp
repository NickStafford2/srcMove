#ifndef INCLUDED_MOVE_DEBUG_HPP
#define INCLUDED_MOVE_DEBUG_HPP

#include <algorithm>
#include <cctype>
#include <iostream>
#include <string>
#include <type_traits>

#include "srcml_node.hpp"

template <typename T>
std::string rpad(T value, std::size_t width, char fill = ' ') {
  std::string s;

  if constexpr (std::is_same_v<std::decay_t<T>, std::string>) {
    s = value;
  } else if constexpr (std::is_same_v<std::decay_t<T>, const char *>) {
    s = value;
  } else {
    // numbers and anything std::to_string supports
    s = std::to_string(value);
  }

  if (s.size() >= width)
    return s;
  s.append(width - s.size(), fill);
  return s;
}

// Turn any whitespace (including \n \t) into a single space, trim ends, and
// truncate.
static std::string clean_text(std::string s, std::size_t max_len = 60) {
  // convert all whitespace to spaces
  for (char &c : s) {
    if (std::isspace(static_cast<unsigned char>(c)))
      c = ' ';
  }

  // collapse consecutive spaces
  std::string out;
  out.reserve(s.size());
  bool prev_space = false;
  for (char c : s) {
    if (c == ' ') {
      if (!prev_space)
        out.push_back(c);
      prev_space = true;
    } else {
      out.push_back(c);
      prev_space = false;
    }
  }

  // trim
  auto not_space = [](unsigned char ch) { return !std::isspace(ch); };
  auto start     = std::find_if(out.begin(), out.end(), not_space);
  auto end       = std::find_if(out.rbegin(), out.rend(), not_space).base();
  if (start >= end)
    return "";

  std::string trimmed(start, end);

  // truncate
  if (trimmed.size() > max_len) {
    trimmed.resize(max_len);
    trimmed += "...";
  }
  return trimmed;
}

static const char *node_kind(const srcml_node &node) {
  if (node.is_start())
    return "START";
  if (node.is_end())
    return "END  ";
  if (node.is_text())
    return "TEXT ";
  return "OTHER";
}

void print_node(const srcml_node &node, std::size_t i = 0) {
  const std::string kind = node_kind(node); // "START"/"END  "/...
  const std::string name = node.full_name();

  // TEXT nodes: show cleaned text, skip whitespace-only
  if (node.is_text() && node.content) {
    std::string cleaned = clean_text(*node.content, 60);
    if (cleaned.empty())
      return;

    std::cout << rpad(i, 6) << " " << rpad(kind, 6) << " " << rpad(name, 20)
              << " " << rpad("attrs=-", 10) << " " << "text=\"" << cleaned
              << "\"" << "\n";
    return;
  }

  // Non-text nodes: show attr count + EMPTY marker
  std::string attrs = "attrs=" + std::to_string(node.attributes.size());

  std::cout << rpad(i, 6) << " " << rpad(kind, 6) << " " << rpad(name, 20)
            << " " << rpad(attrs, 10) << " " << (node.is_empty() ? "EMPTY" : "")
            << "\n";
}

struct Debug_Metrics {
  std::size_t max_tag_stack_depth = 0;

  void print() const {
    std::cout << "[Debug_Metrics] max_tag_stack_depth = " << max_tag_stack_depth
              << "\n";
  }
};

// global instance (C++17 inline ensures single definition)
inline Debug_Metrics debug_metrics;

#endif

/*
locality of behavior
Use several factors to measure the confidence that something is a move.
  assign points to each one.
  can change values depending on user experience feedback.
size of the move
  small lines of code are more likely to be rewritten.
  giant functions moved across files are almost certainly moves
distance to move in the directory tree.
distance to move on page. rows/columns  --position
distance to move between blocks.
Similarity of the two code segments.
*/
