// SPDX-License-Identifier: GPL-3.0-only
#ifndef INCLUDED_MOVEMENT_CLASSIFIER_HPP
#define INCLUDED_MOVEMENT_CLASSIFIER_HPP

#include <string_view>
#include <vector>

#include "location_context.hpp"

namespace srcmove {

// Outcomes under the implemented location policy, not historical edit events.
// Restructured wrapping can still be a move under an AST-parent model.
enum class movement_kind { stationary, relocated, restructured, ambiguous };

enum class movement_classification_reason {
  same_anchor_interval,
  different_file,
  different_semantic_container,
  crossed_stable_sibling,
  ancestor_wrapped,
  ancestor_unwrapped,
  stable_relative_to_relocated_parent,
  incompatible_context,
  insufficient_context,
};

enum class file_observation { same, different, unknown };
enum class semantic_container_observation {
  same_mapped,
  different_mapped,
  unknown,
};
enum class anchor_interval_observation { same, different, crossed, unknown };
enum class ancestor_observation {
  same,
  wrapped,
  unwrapped,
  incompatible,
  unknown,
};

struct movement_observations {
  file_observation file = file_observation::unknown;
  semantic_container_observation semantic_container =
      semantic_container_observation::unknown;
  anchor_interval_observation anchor_interval =
      anchor_interval_observation::unknown;
  ancestor_observation ancestor = ancestor_observation::unknown;
};

struct movement_classification {
  movement_kind change_kind = movement_kind::ambiguous;
  movement_classification_reason reason =
      movement_classification_reason::insufficient_context;
  movement_observations observations;
  // Caller may set stationary relative to a relocated parent plus this flag.
  // This is not a claim that the child retained its file location.
  bool carried_by_parent = false;
};

// Classify endpoint location only. Matching strength, competing endpoints, and
// parent carrying are established by the caller, not inferred from location.
movement_classification classify_movement(
    const endpoint_location_context &before,
    const std::vector<std::string> &before_ancestors,
    const endpoint_location_context &after,
    const std::vector<std::string> &after_ancestors);

// Eligibility predicate for callers that gate one-to-one correspondence proposals;
// it is not the universal selection rule for all reported move groups.
bool move_eligible(const movement_classification &classification) noexcept;

std::string_view to_string(movement_kind value) noexcept;
std::string_view to_string(movement_classification_reason value) noexcept;
std::string_view to_string(file_observation value) noexcept;
std::string_view to_string(semantic_container_observation value) noexcept;
std::string_view to_string(anchor_interval_observation value) noexcept;
std::string_view to_string(ancestor_observation value) noexcept;

} // namespace srcmove

#endif
