#ifndef INCLUDED_CANONICAL_SUBTREE_HPP
#define INCLUDED_CANONICAL_SUBTREE_HPP

#include <cstdint>
#include <string>
#include <vector>

#include "srcml_node.hpp"

namespace srcmove {

struct canonical_options {
  bool ignore_diff_ws              = true;
  bool ignore_whitespace_only_text = true;
  bool ignore_outer_diff_wrapper   = true;
  bool ignore_comments             = true;
  bool normalize_names             = false;
  bool normalize_literals          = false;
};

std::string
canonicalize_diff_region_subtree(const std::vector<srcml_node> &nodes,
                                 const canonical_options       &opt = {},
                                 std::vector<std::uint64_t> *normalized_lines =
                                     nullptr,
                                 std::vector<std::uint64_t> *normalized_tokens =
                                     nullptr);

} // namespace srcmove

#endif
