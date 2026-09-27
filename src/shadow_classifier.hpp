// SPDX-License-Identifier: GPL-3.0-only
#ifndef INCLUDED_SHADOW_CLASSIFIER_HPP
#define INCLUDED_SHADOW_CLASSIFIER_HPP

#include <string_view>
#include <vector>

#include "location_context.hpp"

namespace srcmove {

enum class shadow_change_kind { stationary, relocated, restructured, ambiguous };

enum class shadow_classification_reason {
  same_anchor_interval,
  different_file,
  different_semantic_container,
  crossed_stable_sibling,
  ancestor_wrapped,
  ancestor_unwrapped,
  incompatible_context,
  insufficient_context,
};

enum class file_observation { same, different, unknown };
enum class semantic_container_observation {
  same_mapped,
  different_mapped,
  unknown,
};
enum class anchor_interval_observation { same, crossed, unknown };
enum class ancestor_observation {
  same,
  wrapped,
  unwrapped,
  incompatible,
  unknown,
};

struct shadow_observations {
  file_observation file = file_observation::unknown;
  semantic_container_observation semantic_container =
      semantic_container_observation::unknown;
  anchor_interval_observation anchor_interval =
      anchor_interval_observation::unknown;
  ancestor_observation ancestor = ancestor_observation::unknown;
};

struct shadow_classification {
  shadow_change_kind change_kind = shadow_change_kind::ambiguous;
  shadow_classification_reason reason =
      shadow_classification_reason::insufficient_context;
  shadow_observations observations;
  bool carried_by_parent = false;
};

shadow_classification classify_type1_shadow(
    const endpoint_location_context &before,
    const std::vector<std::string> &before_ancestors,
    const endpoint_location_context &after,
    const std::vector<std::string> &after_ancestors);

std::string_view to_string(shadow_change_kind value) noexcept;
std::string_view to_string(shadow_classification_reason value) noexcept;
std::string_view to_string(file_observation value) noexcept;
std::string_view to_string(semantic_container_observation value) noexcept;
std::string_view to_string(anchor_interval_observation value) noexcept;
std::string_view to_string(ancestor_observation value) noexcept;

} // namespace srcmove

#endif
