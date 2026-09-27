// SPDX-License-Identifier: GPL-3.0-only
#include "move_registry/selection_policy.hpp"

namespace srcmove {
namespace {

constexpr std::uint64_t kStructuralCoverageWeight       = 200;
constexpr std::uint32_t kMinimumConfidenceAdvantage     = 250;
constexpr std::uint64_t kMinimumCoverageNumerator       = 1;
constexpr std::uint64_t kMinimumCoverageDenominator     = 2;
constexpr std::uint64_t kPartitionCoverageNumerator     = 7;
constexpr std::uint64_t kPartitionCoverageDenominator   = 10;
constexpr std::uint64_t kFragmentationScale             = 10;

std::uint64_t scaled_fraction(std::uint64_t value,
                              std::uint64_t numerator,
                              std::uint64_t denominator) {
  return value / denominator * numerator +
         value % denominator * numerator / denominator;
}

} // namespace

bool proposal_rank_better(const proposal_rank_key &lhs,
                          const proposal_rank_key &rhs) {
  const std::uint64_t lhs_rank =
      lhs.utility + kStructuralCoverageWeight * lhs.explanatory_units;
  const std::uint64_t rhs_rank =
      rhs.utility + kStructuralCoverageWeight * rhs.explanatory_units;
  if (lhs_rank != rhs_rank)
    return lhs_rank > rhs_rank;
  if (lhs.utility != rhs.utility)
    return lhs.utility > rhs.utility;
  if (lhs.matched_units != rhs.matched_units)
    return lhs.matched_units > rhs.matched_units;
  if (lhs.evidence_strength != rhs.evidence_strength)
    return lhs.evidence_strength > rhs.evidence_strength;
  if (lhs.source_construct != rhs.source_construct)
    return lhs.source_construct > rhs.source_construct;
  if (lhs.covered_span != rhs.covered_span)
    return lhs.covered_span > rhs.covered_span;
  if (lhs.minimum_id != rhs.minimum_id)
    return lhs.minimum_id < rhs.minimum_id;
  if (lhs.delete_id != rhs.delete_id)
    return lhs.delete_id < rhs.delete_id;
  return lhs.insert_id < rhs.insert_id;
}

bool descendant_bundle_preferred(const descendant_bundle_metrics &m) {
  if (m.child_count < 2 || m.parent_delete_units == 0 ||
      m.parent_insert_units == 0 || m.child_matched_units == 0) {
    return false;
  }
  if (m.child_delete_units * kMinimumCoverageDenominator <
          m.parent_delete_units * kMinimumCoverageNumerator ||
      m.child_insert_units * kMinimumCoverageDenominator <
          m.parent_insert_units * kMinimumCoverageNumerator) {
    return false;
  }
  if (m.child_delete_units * kPartitionCoverageDenominator >=
          m.parent_delete_units * kPartitionCoverageNumerator &&
      m.child_insert_units * kPartitionCoverageDenominator >=
          m.parent_insert_units * kPartitionCoverageNumerator) {
    return false;
  }

  const std::uint64_t bundle_confidence =
      m.child_weighted_confidence / m.child_matched_units;
  if (bundle_confidence <
      static_cast<std::uint64_t>(m.parent_confidence_milli) +
          kMinimumConfidenceAdvantage) {
    return false;
  }

  const std::uint64_t adjusted_utility = scaled_fraction(
      m.child_utility_sum, kFragmentationScale,
      kFragmentationScale + m.child_count - 1);
  return adjusted_utility > m.parent_utility;
}

} // namespace srcmove
