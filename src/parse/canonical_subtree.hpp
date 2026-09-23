#ifndef INCLUDED_CANONICAL_SUBTREE_HPP
#define INCLUDED_CANONICAL_SUBTREE_HPP

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include "srcml_node.hpp"

namespace srcmove {

struct captured_srcml_node;

enum class identifier_normalization { none, consistent };

struct canonical_options {
  bool ignore_diff_ws              = true;
  bool ignore_whitespace_only_text = true;
  bool ignore_outer_diff_wrapper   = true;
  bool ignore_comments             = true;
  bool                     ignore_empty_statements = false;
  bool                     include_structure       = true;
  identifier_normalization identifiers = identifier_normalization::none;
  bool                     normalize_literals      = false;
};

struct canonical_forms {
  std::string                exact;
  std::string                type2_canonical;
  std::vector<std::uint64_t> normalized_lines;
  std::vector<std::uint64_t> normalized_tokens;
};

std::string
canonicalize_diff_region_subtree(const std::vector<srcml_node> &nodes,
                                 const canonical_options       &opt = {},
                                 std::vector<std::uint64_t> *normalized_lines =
                                     nullptr,
                                 std::vector<std::uint64_t> *normalized_tokens =
                                     nullptr);

canonical_forms canonicalize_diff_region_forms(
    const std::vector<captured_srcml_node> &nodes);

canonical_forms canonicalize_diff_region_forms(
    const std::vector<captured_srcml_node> &nodes, std::size_t begin,
    std::size_t end);

} // namespace srcmove

#endif
