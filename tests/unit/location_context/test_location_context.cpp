#include "location_context.hpp"
#include "move_candidate.hpp"
#include "move_registry/candidate_registry.hpp"
#include "region_filter.hpp"
#include "srcml_reader.hpp"

#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using namespace srcmove;

namespace {

void require(bool condition, const char *message) {
  if (!condition)
    throw std::runtime_error(message);
}

bool has_suffix(const std::string &value, const std::string &suffix) {
  return value.size() >= suffix.size() &&
         value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

move_candidate candidate(move_candidate::Kind kind, std::string filename) {
  return move_candidate(kind, 1, std::move(filename), "work();", "work();",
                        "work();", {}, {}, false);
}

const move_candidate *find_candidate(
    const candidate_collection &collection, move_candidate::Kind kind,
    const std::string &raw_text, const std::string &full_name) {
  for (const move_candidate &value : collection.candidates) {
    if (value.kind == kind && value.raw_text == raw_text &&
        value.full_name == full_name) {
      return &value;
    }
  }
  return nullptr;
}

} // namespace

int main(int argc, char **argv) {
  try {
    require(argc == 2, "expected semantic-container fixture path");
    require(split_revision_filename("same.cpp") ==
                std::make_pair(std::string("same.cpp"), std::string("same.cpp")),
            "one archive filename belongs to both revisions");
    require(split_revision_filename("old.cpp|new.cpp") ==
                std::make_pair(std::string("old.cpp"), std::string("new.cpp")),
            "a combined filename must retain both revision paths");
    require(split_revision_filename("old.cpp|") ==
                std::make_pair(std::string("old.cpp"), std::string()),
            "a deleted file has no modified path");
    require(split_revision_filename("|new.cpp") ==
                std::make_pair(std::string(), std::string("new.cpp")),
            "an inserted file has no original path");

    const move_candidate deleted =
        candidate(move_candidate::Kind::del, "source.cpp|destination.cpp");
    const move_candidate inserted =
        candidate(move_candidate::Kind::insert, "source.cpp|destination.cpp");
    require(deleted.location.revision_file == "source.cpp",
            "delete context must use the original file");
    require(inserted.location.revision_file == "destination.cpp",
            "insert context must use the modified file");
    require(!deleted.location.semantic_container_mapped &&
                deleted.location.semantic_container_id.empty() &&
                !deleted.location.anchor_interval_reliable,
            "unobserved structural context must remain explicitly unreliable");

    srcml_reader reader(argv[1]);
    candidate_collection collection =
        collect_candidates_streaming(reader, get_default_filter_options());
    const std::string moved = "int relocated_value = source_value + 17;";
    const move_candidate *moved_delete = find_candidate(
        collection, move_candidate::Kind::del, moved, "decl_stmt");
    const move_candidate *moved_insert = find_candidate(
        collection, move_candidate::Kind::insert, moved, "decl_stmt");
    require(moved_delete != nullptr && moved_insert != nullptr,
            "expected cross-function declaration candidates");
    require(moved_delete->location.semantic_container_mapped &&
                moved_delete->location.semantic_container_label ==
                    "function:source",
            "delete must capture its physical common source function");
    require(moved_insert->location.semantic_container_mapped &&
                moved_insert->location.semantic_container_label ==
                    "function:destination",
            "insert must capture its physical common destination function");
    require(moved_delete->location.semantic_container_id !=
                moved_insert->location.semantic_container_id,
            "distinct physical common functions need distinct stable ids");
    require(moved_delete->location.ancestor_summary_reliable &&
                moved_insert->location.ancestor_summary_reliable &&
                moved_delete->location.ancestor_summary_id ==
                    moved_insert->location.ancestor_summary_id,
            "equivalent side-filtered ancestry must reuse one summary id");

    const std::string wrapped = "int wrapped_value = source_value + 41;";
    const move_candidate *wrapped_delete = find_candidate(
        collection, move_candidate::Kind::del, wrapped, "decl_stmt");
    const move_candidate *wrapped_insert = find_candidate(
        collection, move_candidate::Kind::insert, wrapped, "decl_stmt");
    require(wrapped_delete != nullptr && wrapped_insert != nullptr,
            "expected wrapper-change declaration candidates");
    require(wrapped_delete->location.semantic_container_id ==
                wrapped_insert->location.semantic_container_id &&
                wrapped_delete->location.ancestor_summary_id !=
                    wrapped_insert->location.ancestor_summary_id,
            "one mapped container must retain a side-specific wrapper change");
    require(collection.ancestor_summaries.at(
                wrapped_delete->location.ancestor_summary_id) ==
                std::vector<std::string>{"block"},
            "delete ancestry should contain only the common function block");
    require(collection.ancestor_summaries.at(
                wrapped_insert->location.ancestor_summary_id) ==
                (std::vector<std::string>{"block", "if_stmt", "if", "block"}),
            "insert ancestry should retain the added conditional wrapper");
    require(wrapped_delete->location.anchor_interval_reliable &&
                wrapped_insert->location.anchor_interval_reliable &&
                wrapped_delete->location.previous_common_anchor_id ==
                    wrapped_insert->location.previous_common_anchor_id &&
                wrapped_delete->location.next_common_anchor_id ==
                    wrapped_insert->location.next_common_anchor_id,
            "a wrapper change between common declarations keeps one interval");

    const std::string crossing = "int crossing_value = source_value + 53;";
    const move_candidate *crossing_delete = find_candidate(
        collection, move_candidate::Kind::del, crossing, "decl_stmt");
    const move_candidate *crossing_insert = find_candidate(
        collection, move_candidate::Kind::insert, crossing, "decl_stmt");
    require(crossing_delete != nullptr && crossing_insert != nullptr,
            "expected crossed-anchor declaration candidates");
    require(crossing_delete->location.semantic_container_id ==
                crossing_insert->location.semantic_container_id &&
                crossing_delete->location.anchor_interval_reliable &&
                crossing_insert->location.anchor_interval_reliable &&
                crossing_delete->location.next_common_anchor_id ==
                    crossing_insert->location.previous_common_anchor_id &&
                crossing_delete->location.previous_common_anchor_id !=
                    crossing_insert->location.previous_common_anchor_id &&
                crossing_delete->location.next_common_anchor_id !=
                    crossing_insert->location.next_common_anchor_id,
            "crossing a unique common declaration must change the interval");

    const std::string bounded = "int bounded_value = source_value + 67;";
    const move_candidate *bounded_delete = find_candidate(
        collection, move_candidate::Kind::del, bounded, "decl_stmt");
    const move_candidate *bounded_insert = find_candidate(
        collection, move_candidate::Kind::insert, bounded, "decl_stmt");
    require(bounded_delete != nullptr && bounded_insert != nullptr,
            "expected container-bounded declaration candidates");
    const std::string &bounded_previous =
        bounded_delete->location.previous_common_anchor_id;
    const std::string &bounded_next =
        bounded_delete->location.next_common_anchor_id;
    require(has_suffix(bounded_previous, ":begin") &&
                has_suffix(bounded_next, ":end") &&
                bounded_previous ==
                    bounded_insert->location.previous_common_anchor_id &&
                bounded_next == bounded_insert->location.next_common_anchor_id,
            "repeated and mixed declarations must not become anchors");

    // Only complete, unique, substantive common constructs establish anchors.
    // This matrix also protects declaration collection inside a mixed wrapper.
    for (const auto &scenario : std::vector<std::pair<std::string, int>>{
             {"conditional_crossing", 71}, {"mixed_nested_declaration", 83},
             {"nested_conditional", 97}, {"mixed_outer_conditional", 107}}) {
      const std::string text = "int " + scenario.first + " = " +
                               std::to_string(scenario.second) + ";";
      const auto *before = find_candidate(collection, move_candidate::Kind::del,
                                           text, "decl_stmt");
      const auto *after = find_candidate(collection, move_candidate::Kind::insert,
                                          text, "decl_stmt");
      require(before && after, "expected conditional crossing candidates");
      require(before->location.anchor_interval_reliable &&
                  after->location.anchor_interval_reliable &&
                  before->location.next_common_anchor_id ==
                      after->location.previous_common_anchor_id &&
                  !has_suffix(before->location.next_common_anchor_id, ":end") &&
                  has_suffix(before->location.previous_common_anchor_id, ":begin") &&
                  has_suffix(after->location.next_common_anchor_id, ":end"),
              "unique common conditional or nested declaration must expose crossing");
    }
    {
      const std::string text = "int conditional_stationary = 73;";
      const auto *before = find_candidate(collection, move_candidate::Kind::del,
                                           text, "decl_stmt");
      const auto *after = find_candidate(collection, move_candidate::Kind::insert,
                                          text, "decl_stmt");
      require(before && after, "expected stationary conditional candidates");
      require(before->location.previous_common_anchor_id ==
                  after->location.previous_common_anchor_id &&
                  before->location.next_common_anchor_id ==
                  after->location.next_common_anchor_id &&
                  !has_suffix(before->location.previous_common_anchor_id, ":begin"),
              "staying after a common conditional must retain the same interval");
    }
    for (const auto &scenario : std::vector<std::pair<std::string, int>>{
             {"conditional_repeated", 79}, {"empty_conditional", 101}}) {
      const std::string text = "int " + scenario.first + " = " +
                               std::to_string(scenario.second) + ";";
      for (const auto side : {move_candidate::Kind::del, move_candidate::Kind::insert}) {
        const auto *value = find_candidate(collection, side, text, "decl_stmt");
        require(value, "expected excluded-anchor guard candidates");
        require(has_suffix(value->location.previous_common_anchor_id, ":begin") &&
                    has_suffix(value->location.next_common_anchor_id, ":end"),
                "repeated or comment-only conditional must not establish an anchor");
      }
    }
    for (const auto &scenario : std::vector<std::pair<std::string, int>>{
             {"expression_crossing", 109}, {"expression_assignment", 149},
             {"expression_in_mixed_conditional", 151}}) {
      const std::string text = "int " + scenario.first + " = " +
                               std::to_string(scenario.second) + ";";
      const auto *before = find_candidate(collection, move_candidate::Kind::del,
                                           text, "decl_stmt");
      const auto *after = find_candidate(collection, move_candidate::Kind::insert,
                                          text, "decl_stmt");
      require(before && after, "expected expression crossing candidates");
      require(before->location.anchor_interval_reliable &&
                  after->location.anchor_interval_reliable &&
                  before->location.next_common_anchor_id ==
                      after->location.previous_common_anchor_id &&
                  !has_suffix(before->location.next_common_anchor_id, ":end") &&
                  has_suffix(before->location.previous_common_anchor_id, ":begin") &&
                  has_suffix(after->location.next_common_anchor_id, ":end"),
              "unique common call or assignment must expose a crossing");
    }
    {
      const std::string text = "int expression_stationary = 113;";
      const auto *before = find_candidate(collection, move_candidate::Kind::del,
                                           text, "decl_stmt");
      const auto *after = find_candidate(collection, move_candidate::Kind::insert,
                                          text, "decl_stmt");
      require(before && after, "expected stationary expression candidates");
      require(before->location.anchor_interval_reliable &&
                  after->location.anchor_interval_reliable &&
                  before->location.previous_common_anchor_id ==
                      after->location.previous_common_anchor_id &&
                  before->location.next_common_anchor_id ==
                      after->location.next_common_anchor_id &&
                  !has_suffix(before->location.previous_common_anchor_id, ":begin"),
              "staying after a common call must retain the same interval");
    }
    for (const auto &scenario : std::vector<std::pair<std::string, int>>{
             {"expression_repeated", 127}, {"expression_mixed", 131},
             {"expression_tiny", 137}, {"expression_comment", 139}}) {
      const std::string text = "int " + scenario.first + " = " +
                               std::to_string(scenario.second) + ";";
      for (const auto side : {move_candidate::Kind::del, move_candidate::Kind::insert}) {
        const auto *value = find_candidate(collection, side, text, "decl_stmt");
        require(value, "expected excluded expression anchor candidates");
        require(value->location.anchor_interval_reliable &&
                    has_suffix(value->location.previous_common_anchor_id, ":begin") &&
                    has_suffix(value->location.next_common_anchor_id, ":end"),
                "repeated, mixed, tiny or comment-only expressions must not anchor");
      }
    }
    // Re-reading a nested common tree must assign exactly the same boundaries.
    srcml_reader repeated_reader(argv[1]);
    const auto repeated_collection = collect_candidates_streaming(
        repeated_reader, get_default_filter_options());
    for (const auto &value : collection.candidates) {
      const auto *again = find_candidate(repeated_collection, value.kind,
                                         value.raw_text, value.full_name);
      require(again && value.location.previous_common_anchor_id ==
                           again->location.previous_common_anchor_id &&
                           value.location.next_common_anchor_id ==
                           again->location.next_common_anchor_id,
              "anchor intervals must be deterministic across parses");
    }

    const std::string member = "int member() {return 23;}";
    const move_candidate *member_delete = find_candidate(
        collection, move_candidate::Kind::del, member, "function");
    const move_candidate *member_insert = find_candidate(
        collection, move_candidate::Kind::insert, member, "function");
    require(member_delete != nullptr && member_insert != nullptr,
            "expected exclusive member function candidates");
    require(member_delete->location.semantic_container_label == "class:Owner" &&
                member_insert->location.semantic_container_label == "class:Owner" &&
                member_delete->location.semantic_container_id ==
                    member_insert->location.semantic_container_id,
            "exclusive functions must fall back to their physical common class");

    const std::string unmapped = "int unmapped_value = 31;";
    const move_candidate *unmapped_delete = find_candidate(
        collection, move_candidate::Kind::del, unmapped, "decl_stmt");
    const move_candidate *unmapped_insert = find_candidate(
        collection, move_candidate::Kind::insert, unmapped, "decl_stmt");
    require(unmapped_delete != nullptr && unmapped_insert != nullptr,
            "expected file-root declaration candidates");
    require(!unmapped_delete->location.semantic_container_mapped &&
                !unmapped_insert->location.semantic_container_mapped &&
                !unmapped_delete->location.ancestor_summary_reliable &&
                !unmapped_insert->location.ancestor_summary_reliable,
            "file-root candidates must not manufacture a mapped container");

    const std::size_t wrapped_insert_summary_id =
        wrapped_insert->location.ancestor_summary_id;
    candidate_registry registry;
    registry.add_candidates_for_file(argv[1], std::move(collection.candidates),
                                     std::move(collection.ancestor_summaries));
    require(registry.ancestor_summaries().at(wrapped_insert_summary_id) ==
                (std::vector<std::string>{"block", "if_stmt", "if", "block"}),
            "registry must preserve summaries after parse storage is released");

    const std::size_t original_summary_count =
        registry.ancestor_summaries().size();
    move_candidate later =
        candidate(move_candidate::Kind::del, "later-old.cpp|later-new.cpp");
    later.location.ancestor_summary_reliable = true;
    later.location.ancestor_summary_id = 1;
    const std::size_t later_id = registry.total_record_count();
    registry.add_candidates_for_file(
        "later.xml", std::vector<move_candidate>{std::move(later)},
        std::vector<std::vector<std::string>>{{}, {"while"}});
    const std::size_t rebased_id =
        registry.candidate(later_id).location.ancestor_summary_id;
    require(rebased_id != 1 &&
                registry.ancestor_summaries().at(rebased_id) ==
                    std::vector<std::string>{"while"},
            "independent document summary ids must not collide");
    registry.remove_candidates_for_file("later.xml");
    const bool retained_removed_summary = std::find(
        registry.ancestor_summaries().begin(),
        registry.ancestor_summaries().end(),
        std::vector<std::string>{"while"}) !=
        registry.ancestor_summaries().end();
    require(!retained_removed_summary &&
                registry.ancestor_summaries().size() <= original_summary_count,
            "removal must reclaim summaries no longer referenced by active candidates");

    std::cout << "PASS location context tests\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL location context tests: " << error.what() << "\n";
    return 1;
  }
}
