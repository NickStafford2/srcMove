// SPDX-License-Identifier: GPL-3.0-only
#include "movement_classifier.hpp"

#include <algorithm>

namespace srcmove {
namespace {

template <typename T>
bool is_prefix(const std::vector<T> &prefix, const std::vector<T> &value) {
  return prefix.size() < value.size() &&
         std::equal(prefix.begin(), prefix.end(), value.begin());
}

movement_observations observe(
    const endpoint_location_context &before,
    const std::vector<std::string> &before_ancestors,
    const endpoint_location_context &after,
    const std::vector<std::string> &after_ancestors) {
  movement_observations result;

  if (!before.revision_file.empty() && !after.revision_file.empty()) {
    result.file = before.revision_file == after.revision_file
                      ? file_observation::same
                      : file_observation::different;
  }

  if (before.semantic_container_mapped && after.semantic_container_mapped) {
    result.semantic_container =
        before.semantic_container_id == after.semantic_container_id
            ? semantic_container_observation::same_mapped
            : semantic_container_observation::different_mapped;
  }

  if (before.anchor_interval_reliable && after.anchor_interval_reliable &&
      result.semantic_container ==
          semantic_container_observation::different_mapped) {
    result.anchor_interval = anchor_interval_observation::different;
  } else if (before.anchor_interval_reliable &&
             after.anchor_interval_reliable &&
             result.semantic_container ==
                 semantic_container_observation::same_mapped) {
    const bool same = before.previous_common_anchor_id ==
                          after.previous_common_anchor_id &&
                      before.next_common_anchor_id == after.next_common_anchor_id;
    result.anchor_interval = same ? anchor_interval_observation::same
                                  : anchor_interval_observation::crossed;
  }

  if (before.ancestor_summary_reliable &&
      after.ancestor_summary_reliable) {
    if (!before.ancestor_summary_interpretable ||
        !after.ancestor_summary_interpretable) {
      result.ancestor = ancestor_observation::incompatible;
    } else if (before_ancestors == after_ancestors) {
      result.ancestor = ancestor_observation::same;
    } else if (is_prefix(before_ancestors, after_ancestors)) {
      result.ancestor = ancestor_observation::wrapped;
    } else if (is_prefix(after_ancestors, before_ancestors)) {
      result.ancestor = ancestor_observation::unwrapped;
    } else {
      result.ancestor = ancestor_observation::incompatible;
    }
  }

  return result;
}

movement_classification classified(movement_kind change_kind,
                                 movement_classification_reason reason,
                                 movement_observations observations) {
  return movement_classification{change_kind, reason, observations, false};
}

} // namespace

movement_classification classify_movement(
    const endpoint_location_context &before,
    const std::vector<std::string> &before_ancestors,
    const endpoint_location_context &after,
    const std::vector<std::string> &after_ancestors) {
  const movement_observations observations =
      observe(before, before_ancestors, after, after_ancestors);

  if (observations.file == file_observation::different) {
    return classified(movement_kind::relocated,
                      movement_classification_reason::different_file,
                      observations);
  }
  if (observations.file == file_observation::unknown) {
    return classified(movement_kind::ambiguous,
                      movement_classification_reason::insufficient_context,
                      observations);
  }
  if (observations.semantic_container ==
      semantic_container_observation::different_mapped) {
    return classified(
        movement_kind::relocated,
        movement_classification_reason::different_semantic_container,
        observations);
  }
  if (observations.semantic_container ==
      semantic_container_observation::unknown) {
    return classified(movement_kind::ambiguous,
                      movement_classification_reason::insufficient_context,
                      observations);
  }
  if (observations.anchor_interval == anchor_interval_observation::crossed) {
    return classified(movement_kind::relocated,
                      movement_classification_reason::crossed_stable_sibling,
                      observations);
  }
  if (observations.anchor_interval == anchor_interval_observation::unknown ||
      observations.ancestor == ancestor_observation::unknown) {
    return classified(movement_kind::ambiguous,
                      movement_classification_reason::insufficient_context,
                      observations);
  }
  if (observations.ancestor == ancestor_observation::same) {
    return classified(movement_kind::stationary,
                      movement_classification_reason::same_anchor_interval,
                      observations);
  }
  if (observations.ancestor == ancestor_observation::wrapped) {
    return classified(movement_kind::restructured,
                      movement_classification_reason::ancestor_wrapped,
                      observations);
  }
  if (observations.ancestor == ancestor_observation::unwrapped) {
    return classified(movement_kind::restructured,
                      movement_classification_reason::ancestor_unwrapped,
                      observations);
  }
  return classified(movement_kind::ambiguous,
                    movement_classification_reason::incompatible_context,
                    observations);
}

bool move_eligible(
    const movement_classification &classification) noexcept {
  return classification.change_kind == movement_kind::relocated &&
         !classification.carried_by_parent;
}

#define SRCMOVE_ENUM_STRING_CASE(value, text)                                   \
  case value:                                                                  \
    return text

std::string_view to_string(movement_kind value) noexcept {
  switch (value) {
    SRCMOVE_ENUM_STRING_CASE(movement_kind::stationary, "stationary");
    SRCMOVE_ENUM_STRING_CASE(movement_kind::relocated, "relocated");
    SRCMOVE_ENUM_STRING_CASE(movement_kind::restructured, "restructured");
    SRCMOVE_ENUM_STRING_CASE(movement_kind::ambiguous, "ambiguous");
  }
  return "unknown";
}

std::string_view to_string(movement_classification_reason value) noexcept {
  switch (value) {
    SRCMOVE_ENUM_STRING_CASE(
        movement_classification_reason::same_anchor_interval,
        "same_anchor_interval");
    SRCMOVE_ENUM_STRING_CASE(movement_classification_reason::different_file,
                             "different_file");
    SRCMOVE_ENUM_STRING_CASE(
        movement_classification_reason::different_semantic_container,
        "different_semantic_container");
    SRCMOVE_ENUM_STRING_CASE(
        movement_classification_reason::crossed_stable_sibling,
        "crossed_stable_sibling");
    SRCMOVE_ENUM_STRING_CASE(movement_classification_reason::ancestor_wrapped,
                             "ancestor_wrapped");
    SRCMOVE_ENUM_STRING_CASE(movement_classification_reason::ancestor_unwrapped,
                             "ancestor_unwrapped");
    SRCMOVE_ENUM_STRING_CASE(
        movement_classification_reason::stable_relative_to_relocated_parent,
        "stable_relative_to_relocated_parent");
    SRCMOVE_ENUM_STRING_CASE(
        movement_classification_reason::incompatible_context,
        "incompatible_context");
    SRCMOVE_ENUM_STRING_CASE(
        movement_classification_reason::insufficient_context,
        "insufficient_context");
  }
  return "unknown";
}

std::string_view to_string(file_observation value) noexcept {
  switch (value) {
    SRCMOVE_ENUM_STRING_CASE(file_observation::same, "same");
    SRCMOVE_ENUM_STRING_CASE(file_observation::different, "different");
    SRCMOVE_ENUM_STRING_CASE(file_observation::unknown, "unknown");
  }
  return "unknown";
}

std::string_view to_string(semantic_container_observation value) noexcept {
  switch (value) {
    SRCMOVE_ENUM_STRING_CASE(semantic_container_observation::same_mapped,
                             "same_mapped");
    SRCMOVE_ENUM_STRING_CASE(semantic_container_observation::different_mapped,
                             "different_mapped");
    SRCMOVE_ENUM_STRING_CASE(semantic_container_observation::unknown,
                             "unknown");
  }
  return "unknown";
}

std::string_view to_string(anchor_interval_observation value) noexcept {
  switch (value) {
    SRCMOVE_ENUM_STRING_CASE(anchor_interval_observation::same, "same");
    SRCMOVE_ENUM_STRING_CASE(anchor_interval_observation::different,
                             "different");
    SRCMOVE_ENUM_STRING_CASE(anchor_interval_observation::crossed, "crossed");
    SRCMOVE_ENUM_STRING_CASE(anchor_interval_observation::unknown, "unknown");
  }
  return "unknown";
}

std::string_view to_string(ancestor_observation value) noexcept {
  switch (value) {
    SRCMOVE_ENUM_STRING_CASE(ancestor_observation::same, "same");
    SRCMOVE_ENUM_STRING_CASE(ancestor_observation::wrapped, "wrapped");
    SRCMOVE_ENUM_STRING_CASE(ancestor_observation::unwrapped, "unwrapped");
    SRCMOVE_ENUM_STRING_CASE(ancestor_observation::incompatible,
                             "incompatible");
    SRCMOVE_ENUM_STRING_CASE(ancestor_observation::unknown, "unknown");
  }
  return "unknown";
}

#undef SRCMOVE_ENUM_STRING_CASE

} // namespace srcmove
