#ifndef INCLUDED_CANONICAL_SUBTREE_HPP
#define INCLUDED_CANONICAL_SUBTREE_HPP

#include <string>
#include <vector>

#include "srcml_node.hpp"

namespace srcmove {

struct canonical_options {
  bool ignore_diff_ws              = true;
  bool ignore_whitespace_only_text = true;
  bool ignore_outer_diff_wrapper   = true;
};

std::string
canonicalize_diff_region_subtree(const std::vector<srcml_node> &nodes,
                                 const canonical_options       &opt = {});

} // namespace srcmove

#endif
