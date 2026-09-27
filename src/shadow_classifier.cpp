// SPDX-License-Identifier: GPL-3.0-only
#include "shadow_classifier.hpp"

#include <algorithm>

namespace srcmove {
namespace {

template <typename T>
bool is_prefix(const std::vector<T> &prefix, const std::vector<T> &value) {
  return prefix.size() < value.size() &&
         std::equal(prefix.begin(), prefix.end(), value.begin());
}

shadow_observations observe(
    const endpoint_location_context &before,
    const std::vector<std::string> &before_ancestors,
    const endpoint_location_context &after,
    const std::vector<std::string> &after_ancestors) {
  shadow_observations result;

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

  if (before.anchor_interval_reliable && after.anchor_interval_reliable) {
    const bool same = before.previous_common_anchor_id ==
                          after.previous_common_anchor_id &&
                      before.next_common_anchor_id == after.next_common_anchor_id;
    result.anchor_interval = same ? anchor_interval_observation::same
                                  : anchor_interval_observation::crossed;
  }

  if (before.ancestor_summary_reliable &&
      after.ancestor_summary_reliable) {
    if (before_ancestors == after_ancestors) {
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

shadow_classification classified(shadow_change_kind change_kind,
                                 shadow_classification_reason reason,
                                 shadow_observations observations) {
  return shadow_classification{change_kind, reason, observations, false};
}

} // namespace

shadow_classification classify_type1_shadow(
    const endpoint_location_context &before,
    const std::vector<std::string> &before_ancestors,
    const endpoint_location_context &after,
    const std::vector<std::string> &after_ancestors) {
  const shadow_observations observations =
      observe(before, before_ancestors, after, after_ancestors);

  if (observations.file == file_observation::different) {
    return classified(shadow_change_kind::relocated,
                      shadow_classification_reason::different_file,
                      observations);
  }
  if (observations.file == file_observation::unknown) {
    return classified(shadow_change_kind::ambiguous,
                      shadow_classification_reason::insufficient_context,
                      observations);
  }
  if (observations.semantic_container ==
      semantic_container_observation::different_mapped) {
    return classified(
        shadow_change_kind::relocated,
        shadow_classification_reason::different_semantic_container,
        observations);
  }
  if (observations.semantic_container ==
      semantic_container_observation::unknown) {
    return classified(shadow_change_kind::ambiguous,
                      shadow_classification_reason::insufficient_context,
                      observations);
  }
  if (observations.anchor_interval == anchor_interval_observation::crossed) {
    return classified(shadow_change_kind::relocated,
                      shadow_classification_reason::crossed_stable_sibling,
                      observations);
  }
  if (observations.anchor_interval == anchor_interval_observation::unknown ||
      observations.ancestor == ancestor_observation::unknown) {
    return classified(shadow_change_kind::ambiguous,
                      shadow_classification_reason::insufficient_context,
                      observations);
  }
  if (observations.ancestor == ancestor_observation::same) {
    return classified(shadow_change_kind::stationary,
                      shadow_classification_reason::same_anchor_interval,
                      observations);
  }
  if (observations.ancestor == ancestor_observation::wrapped) {
    return classified(shadow_change_kind::restructured,
                      shadow_classification_reason::ancestor_wrapped,
                      observations);
  }
  if (observations.ancestor == ancestor_observation::unwrapped) {
    return classified(shadow_change_kind::restructured,
                      shadow_classification_reason::ancestor_unwrapped,
                      observations);
  }
  return classified(shadow_change_kind::ambiguous,
                    shadow_classification_reason::incompatible_context,
                    observations);
}

#define SRCMOVE_ENUM_STRING_CASE(value, text)                                   \
  case value:                                                                  \
    return text

std::string_view to_string(shadow_change_kind value) noexcept {
  switch (value) {
    SRCMOVE_ENUM_STRING_CASE(shadow_change_kind::stationary, "stationary");
    SRCMOVE_ENUM_STRING_CASE(shadow_change_kind::relocated, "relocated");
    SRCMOVE_ENUM_STRING_CASE(shadow_change_kind::restructured, "restructured");
    SRCMOVE_ENUM_STRING_CASE(shadow_change_kind::ambiguous, "ambiguous");
  }
  return "unknown";
}

std::string_view to_string(shadow_classification_reason value) noexcept {
  switch (value) {
    SRCMOVE_ENUM_STRING_CASE(
        shadow_classification_reason::same_anchor_interval,
        "same_anchor_interval");
    SRCMOVE_ENUM_STRING_CASE(shadow_classification_reason::different_file,
                             "different_file");
    SRCMOVE_ENUM_STRING_CASE(
        shadow_classification_reason::different_semantic_container,
        "different_semantic_container");
    SRCMOVE_ENUM_STRING_CASE(
        shadow_classification_reason::crossed_stable_sibling,
        "crossed_stable_sibling");
    SRCMOVE_ENUM_STRING_CASE(shadow_classification_reason::ancestor_wrapped,
                             "ancestor_wrapped");
    SRCMOVE_ENUM_STRING_CASE(shadow_classification_reason::ancestor_unwrapped,
                             "ancestor_unwrapped");
    SRCMOVE_ENUM_STRING_CASE(
        shadow_classification_reason::incompatible_context,
        "incompatible_context");
    SRCMOVE_ENUM_STRING_CASE(
        shadow_classification_reason::insufficient_context,
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
