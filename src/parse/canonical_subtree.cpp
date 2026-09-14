#include "canonical_subtree.hpp"

#include <cctype>
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
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

bool is_language_keyword(std::string_view text) {
  // srcML represents both primitive keywords and user-defined type names with
  // <name>. Keep language words stable while normalizing true identifiers.
  static const std::unordered_set<std::string_view> keywords = {
      "abstract", "alignas", "alignof", "and", "as", "asm", "assert",
      "async", "auto", "await", "base", "bool", "boolean", "break",
      "byte", "case", "catch", "char", "checked", "class", "compl",
      "concept", "const", "consteval", "constexpr", "constinit",
      "const_cast", "continue", "co_await", "co_return", "co_yield",
      "decimal", "decltype", "default", "delegate", "delete", "do",
      "double", "dynamic", "else", "enum", "explicit", "export",
      "extends", "extern", "false", "final", "finally", "fixed", "float",
      "for", "foreach", "friend", "goto", "if", "implements", "implicit",
      "import", "in", "inline", "instanceof", "int", "interface",
      "internal", "is", "lock", "long", "module", "mutable", "namespace",
      "native", "new", "noexcept", "not", "nullptr", "null", "object",
      "operator", "or", "out", "override", "package", "params", "private",
      "protected", "public", "readonly", "record", "ref", "register",
      "reinterpret_cast", "requires", "return", "sealed", "short", "signed",
      "sizeof", "stackalloc", "static", "static_assert", "static_cast",
      "strictfp", "string", "struct", "super", "switch", "synchronized",
      "template", "this", "thread_local", "throw", "throws", "transient",
      "true", "try", "typedef", "typeid", "typename", "uint", "ulong",
      "unchecked", "union", "unsafe", "ushort", "using", "var", "virtual",
      "void", "volatile", "wchar_t", "when", "where", "while", "with",
      "xor", "yield"};
  return keywords.find(text) != keywords.end();
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
                                 const canonical_options       &opt,
                                 std::vector<std::uint64_t> *normalized_lines) {
  std::string out;
  std::string normalized_line;
  int         wrapper_depth         = 0;
  bool        skipped_outer_wrapper = false;
  int         comment_depth         = 0;
  int         name_depth            = 0;
  int         literal_depth         = 0;
  std::string current_literal_category;
  std::unordered_map<std::string, std::size_t> normalized_names;

  if (normalized_lines != nullptr) {
    normalized_lines->clear();
  }

  for (const auto &node : nodes) {
    const std::string fn = node.full_name();

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
      out += "T(";
      std::string normalized_text;
      if (opt.normalize_names && name_depth > 0 &&
          !is_language_keyword(*node.content)) {
        const auto [it, inserted] =
            normalized_names.emplace(*node.content, normalized_names.size() + 1);
        (void)inserted;
        normalized_text = "$name" + std::to_string(it->second);
        out += normalized_text;
      } else if (opt.normalize_literals && literal_depth > 0) {
        normalized_text = current_literal_category == "$number"
                              ? number_category(*node.content)
                              : current_literal_category;
        out += normalized_text;
      } else {
        append_escaped(out, *node.content);
        normalized_text = *node.content;
      }
      out += ")";
      append_normalized_code(normalized_line, normalized_lines,
                             normalized_text);
      continue;
    }

    if (node.is_start()) {
      out += "S(";
      out += fn;
      out += ")";
      if (opt.normalize_names && fn == "name") {
        ++name_depth;
      }
      if (opt.normalize_literals && node.name == "literal") {
        ++literal_depth;
        current_literal_category = literal_category(node);
      }
    } else if (node.is_end()) {
      if (opt.normalize_names && fn == "name" && name_depth > 0) {
        --name_depth;
      }
      if (opt.normalize_literals && node.name == "literal" &&
          literal_depth > 0) {
        --literal_depth;
        if (literal_depth == 0) {
          current_literal_category.clear();
        }
      }
      out += "E(";
      out += fn;
      out += ")";
    }
  }

  if (normalized_lines != nullptr && !normalized_line.empty()) {
    normalized_lines->push_back(hash_text(normalized_line));
  }

  return out;
}

} // namespace srcmove
