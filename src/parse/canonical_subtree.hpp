#ifndef INCLUDED_CANONICAL_SUBTREE_HPP
#define INCLUDED_CANONICAL_SUBTREE_HPP

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>
#include <utility>

#include "srcml_node.hpp"

namespace srcmove {

struct captured_srcml_node;

enum class identifier_normalization { none, consistent, blind };

struct canonical_options {
  bool ignore_diff_ws              = true;
  bool ignore_whitespace_only_text = true;
  bool ignore_outer_diff_wrapper   = true;
  bool ignore_comments             = true;
  bool                     include_structure       = true;
  identifier_normalization identifiers = identifier_normalization::none;
  bool                     normalize_literals      = false;
};

struct canonical_forms {
  std::string                exact;
  std::string                type2_canonical;
  bool fragmented_identifier = false;
  std::vector<std::pair<std::string, std::string>> member_accesses; // path,prefix by occurrence
  std::string                names_only_canonical; // exact structure/literals
  std::vector<std::string>   identifier_qualifiers; // exact member access prefix
  std::vector<std::string>   identifier_names; // consistent ordinal order
  std::string                type2b_canonical; // diagnostics only
  std::vector<std::uint64_t> normalized_lines;
  std::vector<std::uint64_t> normalized_tokens;
};

class canonical_forms_builder {
public:
  explicit canonical_forms_builder(bool collect_type2b = false,
                                   bool collect_identity_projection = false);
  ~canonical_forms_builder();

  canonical_forms_builder(canonical_forms_builder &&) noexcept;
  canonical_forms_builder &operator=(canonical_forms_builder &&) noexcept;

  canonical_forms_builder(const canonical_forms_builder &) = delete;
  canonical_forms_builder &operator=(const canonical_forms_builder &) = delete;

  void            consume(const srcml_node &node);
  canonical_forms finish();

private:
  struct implementation;
  std::unique_ptr<implementation> impl;
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
