// SPDX-License-Identifier: GPL-3.0-only
#ifndef INCLUDED_MOVE_SELECTION_POLICY_HPP
#define INCLUDED_MOVE_SELECTION_POLICY_HPP

#include <cstddef>
#include <cstdint>

namespace srcmove {

struct proposal_rank_key {
  std::uint64_t utility          = 0;
  std::size_t   explanatory_units = 0;
  std::size_t   matched_units    = 0;
  int           evidence_strength = 0;
  int           source_construct = 0;
  std::size_t   covered_span     = 0;
  std::size_t   minimum_id       = 0;
  std::size_t   delete_id        = 0;
  std::size_t   insert_id        = 0;
};

bool proposal_rank_better(const proposal_rank_key &lhs,
                          const proposal_rank_key &rhs);

struct descendant_bundle_metrics {
  std::uint64_t parent_utility           = 0;
  std::uint32_t parent_confidence_milli  = 0;
  std::uint64_t parent_delete_units      = 0;
  std::uint64_t parent_insert_units      = 0;
  std::uint64_t child_utility_sum        = 0;
  std::uint64_t child_matched_units      = 0;
  std::uint64_t child_weighted_confidence = 0;
  std::uint64_t child_delete_units       = 0;
  std::uint64_t child_insert_units       = 0;
  std::size_t   child_count              = 0;
};

bool descendant_bundle_preferred(const descendant_bundle_metrics &metrics);

} // namespace srcmove

#endif
