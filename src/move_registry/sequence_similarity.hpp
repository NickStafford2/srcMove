#ifndef INCLUDED_MOVE_SEQUENCE_SIMILARITY_HPP
#define INCLUDED_MOVE_SEQUENCE_SIMILARITY_HPP

#include <cstddef>
#include <cstdint>
#include <vector>

namespace srcmove {

inline constexpr std::size_t kType3ThresholdNumerator   = 9;
inline constexpr std::size_t kType3ThresholdDenominator = 10;

bool can_reach_type3_threshold(std::size_t lhs_size,
                               std::size_t rhs_size) noexcept;

std::size_t bounded_lcs_length(const std::vector<std::uint64_t> &lhs,
                               const std::vector<std::uint64_t> &rhs,
                               std::size_t required_length);

std::size_t type3_lcs_length(const std::vector<std::uint64_t> &lhs,
                             const std::vector<std::uint64_t> &rhs);

} // namespace srcmove

#endif
