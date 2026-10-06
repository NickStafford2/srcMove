#include "movement_classifier.hpp"

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace srcmove;

namespace {

void require(bool condition, const std::string &message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

endpoint_location_context mapped(std::string file, std::string container,
                                 std::string previous, std::string next) {
  endpoint_location_context result;
  result.revision_file = std::move(file);
  result.semantic_container_id = std::move(container);
  result.semantic_container_mapped = true;
  result.previous_common_anchor_id = std::move(previous);
  result.next_common_anchor_id = std::move(next);
  result.structural_region_id = "block:1";
  result.anchor_region_id = "block:1";
  result.structural_region_mapped = true;
  result.common_sibling_prefix_count = 1;
  result.common_sibling_suffix_begin = 1;
  result.anchor_interval_reliable = true;
  result.ancestor_summary_reliable = true;
  result.ancestor_summary_interpretable = true;
  return result;
}

struct classifier_case {
  const char *name;
  endpoint_location_context before;
  std::vector<std::string> before_ancestors;
  endpoint_location_context after;
  std::vector<std::string> after_ancestors;
  movement_kind expected_kind;
  movement_classification_reason expected_reason;
};

} // namespace

int main() {
  try {
    const endpoint_location_context baseline =
        mapped("same.cpp", "function:1", "anchor:lower", "anchor:upper");

    endpoint_location_context different_file = baseline;
    different_file.revision_file = "destination.cpp";

    endpoint_location_context different_container = baseline;
    different_container.semantic_container_id = "function:2";

    endpoint_location_context crossed = baseline;
    crossed.previous_common_anchor_id = "anchor:upper";
    crossed.next_common_anchor_id = "function:1:end";
    crossed.common_sibling_prefix_count = 2;
    crossed.common_sibling_suffix_begin = 2;

    endpoint_location_context unrelated_anchors = baseline;
    unrelated_anchors.previous_common_anchor_id = "unrelated:lower";
    unrelated_anchors.next_common_anchor_id = "unrelated:upper";
    unrelated_anchors.common_sibling_prefix_count = 1;
    unrelated_anchors.common_sibling_suffix_begin = 1;

    endpoint_location_context different_region = baseline;
    different_region.structural_region_id = "block:2";

    endpoint_location_context contained_by_common_control = baseline;
    contained_by_common_control.structural_region_id.clear();
    contained_by_common_control.structural_region_mapped = false;
    contained_by_common_control.previous_common_anchor_id = "function:1:begin";
    contained_by_common_control.next_common_anchor_id = "function:1:end";
    contained_by_common_control.common_sibling_prefix_count = 0;
    contained_by_common_control.common_sibling_suffix_begin = 1;

    endpoint_location_context missing_anchor = baseline;
    missing_anchor.anchor_interval_reliable = false;
    missing_anchor.previous_common_anchor_id.clear();
    missing_anchor.next_common_anchor_id.clear();

    endpoint_location_context unmapped = baseline;
    unmapped.semantic_container_mapped = false;
    unmapped.semantic_container_id.clear();

    endpoint_location_context unknown_file = baseline;
    unknown_file.revision_file.clear();

    endpoint_location_context unknown_ancestor = baseline;
    unknown_ancestor.ancestor_summary_reliable = false;

    endpoint_location_context uninterpretable_ancestor = baseline;
    uninterpretable_ancestor.ancestor_summary_interpretable = false;

    const std::vector<classifier_case> cases{
        {"same stable interval", baseline, {"block"}, baseline, {"block"},
         movement_kind::stationary,
         movement_classification_reason::same_anchor_interval},
        {"different file overrides absent local evidence", baseline, {"block"},
         different_file, {"block"}, movement_kind::relocated,
         movement_classification_reason::different_file},
        {"different mapped container", baseline, {"block"},
         different_container, {"block"}, movement_kind::relocated,
         movement_classification_reason::different_semantic_container},
        {"crossed stable anchor", baseline, {"block"}, crossed, {"block"},
         movement_kind::relocated,
         movement_classification_reason::crossed_stable_sibling},
        {"unrelated anchor boundaries are not displacement", baseline, {"block"},
         unrelated_anchors, {"block"}, movement_kind::ambiguous,
         movement_classification_reason::insufficient_context},
        {"different common source blocks", baseline, {"block", "for", "block"},
         different_region, {"block", "while", "block"}, movement_kind::relocated,
         movement_classification_reason::different_structural_region},
        {"unwrapped from a containing common control", contained_by_common_control,
         {"block", "if_stmt", "else", "block"}, baseline, {"block"},
         movement_kind::restructured,
         movement_classification_reason::ancestor_unwrapped},
        {"wrapped into a containing common control", baseline, {"block"},
         contained_by_common_control, {"block", "if_stmt", "else", "block"},
         movement_kind::restructured,
         movement_classification_reason::ancestor_wrapped},
        {"unwrapping also crosses another sibling", contained_by_common_control,
         {"block", "if_stmt", "else", "block"}, crossed, {"block"},
         movement_kind::relocated,
         movement_classification_reason::crossed_stable_sibling},
        {"meaningful wrapper added", baseline, {"block"}, baseline,
         {"block", "if_stmt", "if", "block"},
         movement_kind::restructured,
         movement_classification_reason::ancestor_wrapped},
        {"meaningful wrapper removed", baseline,
         {"block", "if_stmt", "if", "block"}, baseline, {"block"},
         movement_kind::restructured,
         movement_classification_reason::ancestor_unwrapped},
        {"incompatible ancestry", baseline, {"block", "if_stmt"}, baseline,
         {"block", "while"}, movement_kind::ambiguous,
         movement_classification_reason::incompatible_context},
        {"missing anchor evidence", baseline, {"block"}, missing_anchor,
         {"block"}, movement_kind::ambiguous,
         movement_classification_reason::insufficient_context},
        {"unmapped endpoint", baseline, {"block"}, unmapped, {"block"},
         movement_kind::ambiguous,
         movement_classification_reason::insufficient_context},
        {"unknown revision file", baseline, {"block"}, unknown_file,
         {"block"}, movement_kind::ambiguous,
         movement_classification_reason::insufficient_context},
        {"unknown ancestor evidence", baseline, {"block"}, unknown_ancestor,
         {}, movement_kind::ambiguous,
         movement_classification_reason::insufficient_context},
        {"uninterpretable ancestor", uninterpretable_ancestor, {"block"},
         baseline, {"block"}, movement_kind::ambiguous,
         movement_classification_reason::incompatible_context},
    };

    for (const classifier_case &test : cases) {
      const movement_classification result = classify_movement(
          test.before, test.before_ancestors, test.after, test.after_ancestors);
      require(result.change_kind == test.expected_kind,
              std::string(test.name) + ": unexpected change kind");
      require(result.reason == test.expected_reason,
              std::string(test.name) + ": unexpected reason");
      if (std::string(test.name) == "different mapped container") {
        require(result.observations.anchor_interval ==
                    anchor_interval_observation::different,
                "container-local anchor intervals must be incomparable");
      }
      require(!result.carried_by_parent,
              std::string(test.name) +
                  ": the pure classifier must not infer hierarchy evidence");
    }

    require(to_string(movement_kind::stationary) == "stationary",
            "change-kind strings are part of the diagnostic contract");
    require(to_string(movement_classification_reason::same_anchor_interval) ==
                "same_anchor_interval",
            "reason strings are part of the diagnostic contract");
    require(to_string(
                movement_classification_reason::
                    stable_relative_to_relocated_parent) ==
                "stable_relative_to_relocated_parent",
            "parent-carried reason must remain stable");
    require(to_string(semantic_container_observation::different_mapped) ==
                "different_mapped",
            "observation strings must remain stable");
    require(to_string(anchor_interval_observation::different) == "different",
            "incomparable interval strings must remain stable");

    for (movement_kind kind : {movement_kind::stationary,
                                    movement_kind::restructured,
                                    movement_kind::ambiguous}) {
      movement_classification classification;
      classification.change_kind = kind;
      require(!move_eligible(classification),
              "only positive relocation evidence may emit a Type-1 move");
    }
    movement_classification relocated;
    relocated.change_kind = movement_kind::relocated;
    require(move_eligible(relocated),
            "an independent relocation must remain output-eligible");
    relocated.carried_by_parent = true;
    require(!move_eligible(relocated),
            "a parent-carried child must not emit an independent move");

    std::cout << "PASS shadow classifier tests\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL shadow classifier tests: " << error.what() << "\n";
    return 1;
  }
}
