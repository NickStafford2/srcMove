#include "location_context.hpp"
#include "move_candidate.hpp"

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

move_candidate candidate(move_candidate::Kind kind, std::string filename) {
  return move_candidate(kind, 1, std::move(filename), "work();", "work();",
                        "work();", {}, {}, false);
}

} // namespace

int main() {
  try {
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

    std::cout << "PASS location context tests\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL location context tests: " << error.what() << "\n";
    return 1;
  }
}
