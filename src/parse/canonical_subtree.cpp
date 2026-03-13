#include "canonical_subtree.hpp"

#include <cctype>
#include <string>
#include <string_view>
#include <vector>

namespace srcmove {
namespace {

bool is_diff_wrapper(const srcml_node &node) {
  return node.full_name() == "diff:insert" || node.full_name() == "diff:delete";
}

bool is_diff_ws(const srcml_node &node) {
  return node.full_name() == "diff:ws";
}

bool is_whitespace_only(std::string_view s) {
  for (unsigned char c : s) {
    if (!std::isspace(c))
      return false;
  }
  return true;
}

void append_escaped(std::string &out, std::string_view s) {
  for (char c : s) {
    switch (c) {
    case '\\':
      out += "\\\\";
      break;
    case '\n':
      out += "\\n";
      break;
    case '\t':
      out += "\\t";
      break;
    default:
      out.push_back(c);
      break;
    }
  }
}

} // namespace

std::string
canonicalize_diff_region_subtree(const std::vector<srcml_node> &nodes,
                                 const canonical_options       &opt) {
  std::string out;
  int         wrapper_depth         = 0;
  bool        skipped_outer_wrapper = false;

  for (const auto &node : nodes) {
    const std::string fn = node.full_name();

    if (opt.ignore_outer_diff_wrapper && !skipped_outer_wrapper &&
        (fn == "diff:insert" || fn == "diff:delete")) {
      if (node.is_start()) {
        skipped_outer_wrapper = true;
        wrapper_depth         = 1;
      }
      continue;
    }

    if (wrapper_depth > 0) {
      if (node.is_start() && is_diff_wrapper(node))
        ++wrapper_depth;
      else if (node.is_end() && is_diff_wrapper(node))
        --wrapper_depth;

      if (wrapper_depth == 0)
        continue;
    }

    if (opt.ignore_diff_ws && is_diff_ws(node)) {
      continue;
    }

    if (node.is_text() && node.content) {
      if (opt.ignore_whitespace_only_text &&
          is_whitespace_only(*node.content)) {
        continue;
      }
      out += "T(";
      append_escaped(out, *node.content);
      out += ")";
      continue;
    }

    if (node.is_start()) {
      out += "S(";
      out += fn;
      out += ")";
    } else if (node.is_end()) {
      out += "E(";
      out += fn;
      out += ")";
    }
  }

  return out;
}

} // namespace srcmove
