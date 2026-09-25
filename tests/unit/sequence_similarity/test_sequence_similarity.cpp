#include "move_registry/sequence_similarity.hpp"

#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

using namespace srcmove;

namespace {

void require(bool condition, const char *message) {
  if (!condition)
    throw std::runtime_error(message);
}

} // namespace

int main() {
  try {
    const std::vector<std::uint64_t> baseline{0, 1, 2, 3, 4,
                                               5, 6, 7, 8, 9};
    const std::vector<std::uint64_t> ninety_percent{0, 1, 2, 3, 4,
                                                     5, 6, 7, 8, 99};
    const std::vector<std::uint64_t> eighty_percent{0, 1, 2, 3, 4,
                                                     5, 6, 7, 98, 99};

    require(can_reach_type3_threshold(9, 10),
            "a 9:10 size ratio should reach the Type-3 threshold");
    require(!can_reach_type3_threshold(8, 10),
            "an 8:10 size ratio should not reach the Type-3 threshold");
    require(type3_lcs_length(baseline, ninety_percent) == 9,
            "90% sequence similarity should be accepted");
    require(type3_lcs_length(baseline, eighty_percent) == 0,
            "similarity below 90% should be rejected");

    std::cout << "PASS sequence similarity tests\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL sequence similarity tests: " << error.what() << "\n";
    return 1;
  }
}
