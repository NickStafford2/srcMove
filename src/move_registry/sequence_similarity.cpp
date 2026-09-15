#include "move_registry/sequence_similarity.hpp"

#include <algorithm>
#include <vector>

namespace srcmove {
namespace {

std::size_t required_common_length(std::size_t maximum_size) noexcept {
  return (maximum_size * kType3ThresholdNumerator +
          kType3ThresholdDenominator - 1) /
         kType3ThresholdDenominator;
}

} // namespace

bool can_reach_type3_threshold(std::size_t lhs_size,
                               std::size_t rhs_size) noexcept {
  if (lhs_size == 0 || rhs_size == 0) {
    return false;
  }
  return std::min(lhs_size, rhs_size) >=
         required_common_length(std::max(lhs_size, rhs_size));
}

std::size_t bounded_lcs_length(const std::vector<std::uint64_t> &lhs,
                               const std::vector<std::uint64_t> &rhs,
                               std::size_t required_length) {
  if (required_length == 0) {
    return 0;
  }

  const std::vector<std::uint64_t> *rows = &lhs;
  const std::vector<std::uint64_t> *cols = &rhs;
  if (rows->size() > cols->size()) {
    std::swap(rows, cols);
  }

  std::vector<std::size_t> previous(cols->size() + 1, 0);
  std::vector<std::size_t> current(cols->size() + 1, 0);

  for (std::size_t i = 1; i <= rows->size(); ++i) {
    current[0] = 0;
    for (std::size_t j = 1; j <= cols->size(); ++j) {
      if ((*rows)[i - 1] == (*cols)[j - 1]) {
        current[j] = previous[j - 1] + 1;
      } else {
        current[j] = std::max(previous[j], current[j - 1]);
      }
    }

    const std::size_t remaining_rows = rows->size() - i;
    if (current.back() + remaining_rows < required_length) {
      return 0;
    }
    previous.swap(current);
  }

  return previous.back();
}

std::size_t type3_lcs_length(const std::vector<std::uint64_t> &lhs,
                             const std::vector<std::uint64_t> &rhs) {
  if (!can_reach_type3_threshold(lhs.size(), rhs.size())) {
    return 0;
  }

  const std::size_t required =
      required_common_length(std::max(lhs.size(), rhs.size()));
  const std::size_t common = bounded_lcs_length(lhs, rhs, required);
  return common >= required ? common : 0;
}

} // namespace srcmove
