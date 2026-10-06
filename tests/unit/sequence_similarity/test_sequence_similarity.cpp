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

void test_nine_to_ten_size_ratio_can_reach_threshold() {
  require(can_reach_type3_threshold(9, 10),
          "a 9:10 size ratio should reach the Type-3 threshold");
}

void test_eight_to_ten_size_ratio_cannot_reach_threshold() {
  require(!can_reach_type3_threshold(8, 10),
          "an 8:10 size ratio should not reach the Type-3 threshold");
}

void test_sequence_with_one_changed_unit_is_accepted() {
  const std::vector<std::uint64_t> original{0, 1, 2, 3, 4, 5, 6, 7, 8, 9};
  const std::vector<std::uint64_t> one_changed_unit{0, 1, 2, 3, 4,
                                                 5, 6, 7, 8, 99};

  require(type3_lcs_length(original, one_changed_unit) == 9,
          "90% sequence similarity should be accepted");
}

void test_sequence_with_two_changed_units_is_rejected() {
  const std::vector<std::uint64_t> original{0, 1, 2, 3, 4, 5, 6, 7, 8, 9};
  const std::vector<std::uint64_t> two_changed_units{0, 1, 2, 3, 4,
                                                  5, 6, 7, 98, 99};

  require(type3_lcs_length(original, two_changed_units) == 0,
          "similarity below 90% should be rejected");
}

} // namespace

int main() {
  try {
    test_nine_to_ten_size_ratio_can_reach_threshold();
    test_eight_to_ten_size_ratio_cannot_reach_threshold();
    test_sequence_with_one_changed_unit_is_accepted();
    test_sequence_with_two_changed_units_is_rejected();

    std::cout << "PASS sequence similarity tests\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL sequence similarity tests: " << error.what() << "\n";
    return 1;
  }
}
