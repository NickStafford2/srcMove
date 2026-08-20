// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file group_selection.hpp
 *
 * Selection state and overlap-suppression policy for pending content groups.
 */
#ifndef INCLUDED_MOVE_GROUP_SELECTION_HPP
#define INCLUDED_MOVE_GROUP_SELECTION_HPP

#include <cstddef>
#include <string_view>
#include <unordered_set>
#include <vector>

#include "move_candidate.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/move_buckets.hpp"
#include "move_registry/pending_group.hpp"

namespace srcmove {

class group_selection {
public:
  explicit group_selection(std::size_t candidate_count);

  bool candidate_is_suppressed(const move_candidate &candidate) const;
  bool group_is_fully_suppressed(const pending_group      &group,
                                 const candidate_registry &registry) const;
  bool id_is_used(candidate_id id) const;

  void mark_selected(const pending_group      &group,
                     const candidate_registry &registry);

private:
  struct covered_span {
    move_candidate::Kind kind = move_candidate::Kind::del;
    std::string_view     filename;
    std::size_t          start_idx = 0;
    std::size_t          end_idx   = 0;
  };

  static bool span_contains_candidate(const covered_span   &span,
                                      const move_candidate &candidate);
  static bool candidate_contains_span(const move_candidate &candidate,
                                      const covered_span   &span);
  void        mark_group_covered(const pending_group      &group,
                                 const candidate_registry &registry);

  std::unordered_set<candidate_id> used_ids_;
  std::vector<covered_span>        covered_;
};

bool group_selection_order_less(const pending_group      &lhs,
                                const pending_group      &rhs,
                                const candidate_registry &registry);

std::vector<candidate_id>
filter_unselected_ids(const std::vector<candidate_id> &ids,
                      const candidate_registry        &registry,
                      const group_selection           &selection);

} // namespace srcmove

#endif
