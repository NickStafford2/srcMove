#include "canonical_subtree.hpp"

#include <cctype>
#include <cstdint>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "parse/diff_region.hpp"

namespace srcmove {
namespace {

bool is_diff_wrapper(const srcml_node &node) {
  const std::string full_name = node.full_name();
  return full_name == "diff:insert" || full_name == "diff:delete" ||
         full_name == "diff:common";
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

class canonical_builder {
public:
  canonical_builder(const canonical_options    &options,
                    bool                        collect_output,
                    std::vector<std::uint64_t> *normalized_lines = nullptr,
                    std::vector<std::uint64_t> *normalized_tokens = nullptr)
      : opt(options), collect_output(collect_output), lines(normalized_lines),
        tokens(normalized_tokens) {
    if (lines != nullptr) {
      lines->clear();
    }
    if (tokens != nullptr) {
      tokens->clear();
    }
  }

  void consume(const srcml_node &node, const std::string &full_name) {
    if (ignored_empty_depth > 0) {
      if (node.is_start()) {
        ++ignored_empty_depth;
      } else if (node.is_end()) {
        --ignored_empty_depth;
      }
      return;
    }

    if (opt.ignore_empty_statements && node.is_start() &&
        node.name == "empty_stmt") {
      ignored_empty_depth = 1;
      return;
    }

    if (comment_depth > 0) {
      if (node.is_start() && node.name == "comment") {
        ++comment_depth;
      } else if (node.is_end() && node.name == "comment") {
        --comment_depth;
      }
      return;
    }

    if (opt.ignore_comments && node.is_start() && node.name == "comment") {
      comment_depth = 1;
      return;
    }

    // srcDiff wrappers describe revision membership; they are not source
    // structure. Treat every wrapper as transparent so equivalent source does
    // not acquire a different identity solely from nested diff boundaries.
    if (opt.ignore_outer_diff_wrapper && is_diff_wrapper(node)) {
      return;
    }

    if (opt.ignore_diff_ws && is_diff_ws(node)) {
      return;
    }

    if (node.is_text() && node.content) {
      consume_text(*node.content);
      return;
    }

    if (node.is_start()) {
      if (collect_output && opt.include_structure) {
        out += "S(";
        out += full_name;
        out += ")";
      }
      if (opt.normalize_literals && node.name == "literal") {
        ++literal_depth;
        current_literal_category = literal_category(node);
        literal_value_emitted    = false;
      }
      element_stack.push_back(full_name);
    } else if (node.is_end()) {
      if (opt.normalize_literals && node.name == "literal" &&
          literal_depth > 0) {
        --literal_depth;
        if (literal_depth == 0) {
          current_literal_category.clear();
          literal_value_emitted = false;
        }
      }
      if (collect_output && opt.include_structure) {
        out += "E(";
        out += full_name;
        out += ")";
      }
      if (!element_stack.empty()) {
        element_stack.pop_back();
      }
    }
  }

  std::string finish() {
    if (lines != nullptr && !normalized_line.empty()) {
      lines->push_back(hash_text(normalized_line));
    }
    return std::move(out);
  }

private:
  void consume_text(const std::string &text) {
    if (opt.ignore_whitespace_only_text && is_whitespace_only(text)) {
      return;
    }
    if (opt.normalize_literals && literal_depth > 0 &&
        literal_value_emitted) {
      return;
    }
    if (collect_output && opt.include_structure) {
      out += "T(";
    }

    std::string normalized_text;
    std::string similarity_text;
    const bool normalizable_name =
        !element_stack.empty() && element_stack.back() == "name";
    if (opt.identifiers == identifier_normalization::consistent &&
        normalizable_name) {
      const auto [it, inserted] =
          normalized_names.emplace(text, normalized_names.size() + 1);
      (void)inserted;
      normalized_text = "$name" + std::to_string(it->second);
      similarity_text = normalized_text;
      if (collect_output) {
        out += normalized_text;
      }
    } else if (opt.normalize_literals && literal_depth > 0) {
      literal_value_emitted = true;
      normalized_text = current_literal_category == "$number"
                            ? number_category(text)
                            : current_literal_category;
      if (collect_output) {
        out += normalized_text;
      }
    } else {
      if (collect_output) {
        if (opt.include_structure) {
          append_escaped(out, text);
        } else {
          append_compact(out, text);
        }
      }
      normalized_text = text;
    }

    if (collect_output && opt.include_structure) {
      out += ")";
    }
    append_normalized_code(normalized_line, lines, normalized_text);
    append_normalized_token(tokens,
                            similarity_text.empty() ? normalized_text
                                                    : similarity_text);
  }

  canonical_options opt;
  bool collect_output;
  std::vector<std::uint64_t> *lines;
  std::vector<std::uint64_t> *tokens;
  std::string                 out;
  std::string                 normalized_line;
  int         comment_depth         = 0;
  int         ignored_empty_depth   = 0;
  int         literal_depth         = 0;
  bool        literal_value_emitted = false;
  std::string current_literal_category;
  std::unordered_map<std::string, std::size_t> normalized_names;
  std::vector<std::string> element_stack;
};

} // namespace

struct canonical_forms_builder::implementation {
  implementation()
      : exact(exact_options, true), normalized(normalized_options(), false,
                                               &forms.normalized_lines,
                                               &forms.normalized_tokens),
        lexical(lexical_options(), true) {}

  static canonical_options normalized_options() {
    canonical_options options;
    options.identifiers        = identifier_normalization::consistent;
    options.normalize_literals = true;
    return options;
  }

  static canonical_options lexical_options() {
    canonical_options options = normalized_options();
    options.ignore_empty_statements = true;
    options.include_structure       = false;
    return options;
  }

  canonical_options exact_options;
  canonical_forms   forms;
  canonical_builder exact;
  canonical_builder normalized;
  canonical_builder lexical;
};

canonical_forms_builder::canonical_forms_builder()
    : impl(std::make_unique<implementation>()) {}

canonical_forms_builder::~canonical_forms_builder() = default;

canonical_forms_builder::canonical_forms_builder(
    canonical_forms_builder &&) noexcept = default;

canonical_forms_builder &canonical_forms_builder::operator=(
    canonical_forms_builder &&) noexcept = default;

void canonical_forms_builder::consume(const srcml_node &node) {
  const std::string full_name = node.full_name();
  impl->exact.consume(node, full_name);
  impl->normalized.consume(node, full_name);
  impl->lexical.consume(node, full_name);
}

canonical_forms canonical_forms_builder::finish() {
  impl->forms.exact = impl->exact.finish();
  (void)impl->normalized.finish();
  impl->forms.type2_canonical = impl->lexical.finish();
  return std::move(impl->forms);
}

std::string
canonicalize_diff_region_subtree(const std::vector<srcml_node> &nodes,
                                 const canonical_options       &opt,
                                 std::vector<std::uint64_t> *normalized_lines,
                                 std::vector<std::uint64_t> *normalized_tokens) {
  canonical_builder builder(opt, true, normalized_lines, normalized_tokens);
  for (const auto &node : nodes) {
    builder.consume(node, node.full_name());
  }
  return builder.finish();
}

canonical_forms canonicalize_diff_region_forms(
    const std::vector<captured_srcml_node> &nodes) {
  return canonicalize_diff_region_forms(nodes, 0, nodes.size());
}

canonical_forms canonicalize_diff_region_forms(
    const std::vector<captured_srcml_node> &nodes, std::size_t begin,
    std::size_t end) {
  canonical_forms_builder builder;

  for (std::size_t i = begin; i < end; ++i) {
    builder.consume(nodes[i].node);
  }
  return builder.finish();
}

} // namespace srcmove
