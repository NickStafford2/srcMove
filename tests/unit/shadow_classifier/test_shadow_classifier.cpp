#include "shadow_classifier.hpp"

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
  result.anchor_interval_reliable = true;
  result.ancestor_summary_reliable = true;
  return result;
}

struct classifier_case {
  const char *name;
  endpoint_location_context before;
  std::vector<std::string> before_ancestors;
  endpoint_location_context after;
  std::vector<std::string> after_ancestors;
  shadow_change_kind expected_kind;
  shadow_classification_reason expected_reason;
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

    const std::vector<classifier_case> cases{
        {"same stable interval", baseline, {"block"}, baseline, {"block"},
         shadow_change_kind::stationary,
         shadow_classification_reason::same_anchor_interval},
        {"different file overrides absent local evidence", baseline, {"block"},
         different_file, {"block"}, shadow_change_kind::relocated,
         shadow_classification_reason::different_file},
        {"different mapped container", baseline, {"block"},
         different_container, {"block"}, shadow_change_kind::relocated,
         shadow_classification_reason::different_semantic_container},
        {"crossed stable anchor", baseline, {"block"}, crossed, {"block"},
         shadow_change_kind::relocated,
         shadow_classification_reason::crossed_stable_sibling},
        {"meaningful wrapper added", baseline, {"block"}, baseline,
         {"block", "if_stmt", "if", "block"},
         shadow_change_kind::restructured,
         shadow_classification_reason::ancestor_wrapped},
        {"meaningful wrapper removed", baseline,
         {"block", "if_stmt", "if", "block"}, baseline, {"block"},
         shadow_change_kind::restructured,
         shadow_classification_reason::ancestor_unwrapped},
        {"incompatible ancestry", baseline, {"block", "if_stmt"}, baseline,
         {"block", "while"}, shadow_change_kind::ambiguous,
         shadow_classification_reason::incompatible_context},
        {"missing anchor evidence", baseline, {"block"}, missing_anchor,
         {"block"}, shadow_change_kind::ambiguous,
         shadow_classification_reason::insufficient_context},
        {"unmapped endpoint", baseline, {"block"}, unmapped, {"block"},
         shadow_change_kind::ambiguous,
         shadow_classification_reason::insufficient_context},
        {"unknown revision file", baseline, {"block"}, unknown_file,
         {"block"}, shadow_change_kind::ambiguous,
         shadow_classification_reason::insufficient_context},
        {"unknown ancestor evidence", baseline, {"block"}, unknown_ancestor,
         {}, shadow_change_kind::ambiguous,
         shadow_classification_reason::insufficient_context},
    };

    for (const classifier_case &test : cases) {
      const shadow_classification result = classify_type1_shadow(
          test.before, test.before_ancestors, test.after, test.after_ancestors);
      require(result.change_kind == test.expected_kind,
              std::string(test.name) + ": unexpected change kind");
      require(result.reason == test.expected_reason,
              std::string(test.name) + ": unexpected reason");
      require(!result.carried_by_parent,
              std::string(test.name) +
                  ": parent carrying is unsupported in this slice");
    }

    require(to_string(shadow_change_kind::stationary) == "stationary",
            "change-kind strings are part of the diagnostic contract");
    require(to_string(shadow_classification_reason::same_anchor_interval) ==
                "same_anchor_interval",
            "reason strings are part of the diagnostic contract");
    require(to_string(semantic_container_observation::different_mapped) ==
                "different_mapped",
            "observation strings must remain stable");

    std::cout << "PASS shadow classifier tests\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL shadow classifier tests: " << error.what() << "\n";
    return 1;
  }
}
