#include "canonical_subtree.hpp"

#include <cctype>
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
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

std::uint64_t hash_text(std::string_view text) {
  std::uint64_t hash = 14695981039346656037ull;
  for (unsigned char c : text) {
    hash ^= static_cast<std::uint64_t>(c);
    hash *= 1099511628211ull;
  }
  return hash;
}

std::string literal_category(const srcml_node &node) {
  const std::string *type = node.get_attribute_value("type");
  if (type == nullptr) {
    return "$literal";
  }
  if (*type == "number") {
    return "$number";
  }
  if (*type == "string") {
    return "$string";
  }
  if (*type == "char") {
    return "$character";
  }
  if (*type == "boolean") {
    return "$boolean";
  }
  if (*type == "null") {
    return "$null";
  }
  return "$" + *type;
}

std::string number_category(std::string_view text) {
  std::size_t begin = 0;
  if (!text.empty() && (text.front() == '+' || text.front() == '-')) {
    begin = 1;
  }

  const bool hexadecimal =
      text.size() >= begin + 2 && text[begin] == '0' &&
      (text[begin + 1] == 'x' || text[begin + 1] == 'X');
  for (std::size_t i = begin; i < text.size(); ++i) {
    const char c = text[i];
    if (c == '.' || c == 'p' || c == 'P' ||
        (!hexadecimal && (c == 'e' || c == 'E')) || c == 'f' || c == 'F' ||
        c == 'd' || c == 'D' || c == 'm' || c == 'M') {
      return "$floating";
    }
  }
  return "$integer";
}

void append_normalized_code(std::string                 &line,
                            std::vector<std::uint64_t>  *lines,
                            std::string_view             text) {
  if (lines == nullptr) {
    return;
  }

  for (unsigned char c : text) {
    if (std::isspace(c)) {
      continue;
    }
    line.push_back(static_cast<char>(c));
    if (c == ';' || c == '{' || c == '}') {
      lines->push_back(hash_text(line));
      line.clear();
    }
  }
}

void append_normalized_token(std::vector<std::uint64_t> *tokens,
                             std::string_view             text) {
  if (tokens == nullptr) {
    return;
  }

  std::string compact;
  compact.reserve(text.size());
  for (unsigned char c : text) {
    if (!std::isspace(c)) {
      compact.push_back(static_cast<char>(c));
    }
  }
  if (!compact.empty()) {
    tokens->push_back(hash_text(compact));
  }
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

void append_compact(std::string &out, std::string_view text) {
  for (unsigned char c : text) {
    if (!std::isspace(c)) {
      out.push_back(static_cast<char>(c));
    }
  }
}

} // namespace

std::string
canonicalize_diff_region_subtree(const std::vector<srcml_node> &nodes,
                                 const canonical_options       &opt,
                                 std::vector<std::uint64_t> *normalized_lines,
                                 std::vector<std::uint64_t> *normalized_tokens) {
  std::string out;
  std::string normalized_line;
  int         wrapper_depth         = 0;
  bool        skipped_outer_wrapper = false;
  int         comment_depth         = 0;
  int         ignored_empty_depth   = 0;
  int         literal_depth         = 0;
  bool        literal_value_emitted = false;
  std::string current_literal_category;
  std::unordered_map<std::string, std::size_t> normalized_names;
  std::vector<std::string> element_stack;

  if (normalized_lines != nullptr) {
    normalized_lines->clear();
  }
  if (normalized_tokens != nullptr) {
    normalized_tokens->clear();
  }

  for (const auto &node : nodes) {
    const std::string fn = node.full_name();

    if (ignored_empty_depth > 0) {
      if (node.is_start()) {
        ++ignored_empty_depth;
      } else if (node.is_end()) {
        --ignored_empty_depth;
      }
      continue;
    }

    if (opt.ignore_empty_statements && node.is_start() &&
        node.name == "empty_stmt") {
      ignored_empty_depth = 1;
      continue;
    }

    if (comment_depth > 0) {
      if (node.is_start() && node.name == "comment") {
        ++comment_depth;
      } else if (node.is_end() && node.name == "comment") {
        --comment_depth;
      }
      continue;
    }

    if (opt.ignore_comments && node.is_start() && node.name == "comment") {
      comment_depth = 1;
      continue;
    }

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
      if (opt.normalize_literals && literal_depth > 0 &&
          literal_value_emitted) {
        continue;
      }
      if (opt.include_structure) {
        out += "T(";
      }
      std::string normalized_text;
      std::string similarity_text;
      const bool normalizable_name =
          !element_stack.empty() && element_stack.back() == "name";
      if (opt.identifiers == identifier_normalization::consistent &&
          normalizable_name) {
        const auto [it, inserted] =
            normalized_names.emplace(*node.content, normalized_names.size() + 1);
        (void)inserted;
        normalized_text = "$name" + std::to_string(it->second);
        similarity_text = normalized_text;
        out += normalized_text;
      } else if (opt.normalize_literals && literal_depth > 0) {
        literal_value_emitted = true;
        normalized_text = current_literal_category == "$number"
                              ? number_category(*node.content)
                              : current_literal_category;
        out += normalized_text;
      } else {
        if (opt.include_structure) {
          append_escaped(out, *node.content);
        } else {
          append_compact(out, *node.content);
        }
        normalized_text = *node.content;
      }
      if (opt.include_structure) {
        out += ")";
      }
      append_normalized_code(normalized_line, normalized_lines,
                             normalized_text);
      append_normalized_token(normalized_tokens,
                              similarity_text.empty() ? normalized_text
                                                      : similarity_text);
      continue;
    }

    if (node.is_start()) {
      if (opt.include_structure) {
        out += "S(";
        out += fn;
        out += ")";
      }
      if (opt.normalize_literals && node.name == "literal") {
        ++literal_depth;
        current_literal_category = literal_category(node);
        literal_value_emitted = false;
      }
      element_stack.push_back(fn);
    } else if (node.is_end()) {
      if (opt.normalize_literals && node.name == "literal" &&
          literal_depth > 0) {
        --literal_depth;
        if (literal_depth == 0) {
          current_literal_category.clear();
          literal_value_emitted = false;
        }
      }
      if (opt.include_structure) {
        out += "E(";
        out += fn;
        out += ")";
      }
      if (!element_stack.empty()) {
        element_stack.pop_back();
      }
    }
  }

  if (normalized_lines != nullptr && !normalized_line.empty()) {
    normalized_lines->push_back(hash_text(normalized_line));
  }

  return out;
}

} // namespace srcmove
