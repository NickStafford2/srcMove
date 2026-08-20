// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file group_selection.cpp
 */
#include "move_registry/group_selection.hpp"

#include <algorithm>

namespace srcmove {

bool has_both_sides(const pending_group &group) {
  return !group.del_ids.empty() && !group.ins_ids.empty();
}

bool is_one_to_one(const pending_group &group) {
  return group.del_ids.size() == 1 && group.ins_ids.size() == 1;
}

group_selection::group_selection(std::size_t candidate_count) {
  used_ids_.reserve(candidate_count);
  covered_.reserve(candidate_count);
}

bool group_selection::candidate_is_suppressed(
    const move_candidate &candidate) const {
  for (const covered_span &span : covered_) {
    if (span_contains_candidate(span, candidate)) {
      return true;
    }

    if (candidate.role != move_candidate::Role::structural_child &&
        candidate_contains_span(candidate, span)) {
      return true;
    }
  }

  return false;
}

bool group_selection::group_is_fully_suppressed(
    const pending_group &group, const candidate_registry &registry) const {
  if (!has_both_sides(group)) {
    return false;
  }

  for (candidate_id id : group.del_ids) {
    if (!candidate_is_suppressed(registry.candidate(id))) {
      return false;
    }
  }

  for (candidate_id id : group.ins_ids) {
    if (!candidate_is_suppressed(registry.candidate(id))) {
      return false;
    }
  }

  return true;
}

bool group_selection::id_is_used(candidate_id id) const {
  return used_ids_.find(id) != used_ids_.end();
}

void group_selection::mark_selected(const pending_group      &group,
                                    const candidate_registry &registry) {
  if (!has_both_sides(group)) {
    return;
  }

  used_ids_.insert(group.del_ids.begin(), group.del_ids.end());
  used_ids_.insert(group.ins_ids.begin(), group.ins_ids.end());
  mark_group_covered(group, registry);
}

bool group_selection::span_contains_candidate(
    const covered_span &span, const move_candidate &candidate) {
  return span.kind == candidate.kind && span.filename == candidate.filename &&
         span.start_idx <= candidate.start_idx &&
         candidate.end_idx <= span.end_idx;
}

bool group_selection::candidate_contains_span(
    const move_candidate &candidate, const covered_span &span) {
  return span.kind == candidate.kind && span.filename == candidate.filename &&
         candidate.start_idx <= span.start_idx &&
         span.end_idx <= candidate.end_idx;
}

void group_selection::mark_group_covered(const pending_group      &group,
                                         const candidate_registry &registry) {
  for (candidate_id id : group.del_ids) {
    const move_candidate &candidate = registry.candidate(id);
    covered_.push_back(covered_span{candidate.kind, candidate.filename,
                                    candidate.start_idx, candidate.end_idx});
  }

  for (candidate_id id : group.ins_ids) {
    const move_candidate &candidate = registry.candidate(id);
    covered_.push_back(covered_span{candidate.kind, candidate.filename,
                                    candidate.start_idx, candidate.end_idx});
  }
}

namespace {

std::size_t candidate_span_size(const move_candidate &candidate) {
  if (candidate.end_idx < candidate.start_idx) {
    return 0;
  }
  return candidate.end_idx - candidate.start_idx + 1;
}

std::size_t group_span_size(const pending_group      &group,
                            const candidate_registry &registry) {
  std::size_t size = 0;

  for (candidate_id id : group.del_ids) {
    size += candidate_span_size(registry.candidate(id));
  }

  for (candidate_id id : group.ins_ids) {
    size += candidate_span_size(registry.candidate(id));
  }

  return size;
}

candidate_id min_group_id(const pending_group &group) {
  candidate_id min_id = static_cast<candidate_id>(-1);

  for (candidate_id id : group.del_ids) {
    min_id = std::min(min_id, id);
  }

  for (candidate_id id : group.ins_ids) {
    min_id = std::min(min_id, id);
  }

  return min_id;
}

bool any_single_child_wrapper(const pending_group      &group,
                              const candidate_registry &registry) {
  for (candidate_id id : group.del_ids) {
    const move_candidate &candidate = registry.candidate(id);
    if (candidate.role == move_candidate::Role::single_child_wrapper) {
      return true;
    }
  }

  for (candidate_id id : group.ins_ids) {
    const move_candidate &candidate = registry.candidate(id);
    if (candidate.role == move_candidate::Role::single_child_wrapper) {
      return true;
    }
  }

  return false;
}

enum class selection_tier : int {
  primary               = 1,
  single_child_fallback = 2,
};

selection_tier group_selection_tier(const pending_group      &group,
                                    const candidate_registry &registry) {
  if (any_single_child_wrapper(group, registry)) {
    return selection_tier::single_child_fallback;
  }
  return selection_tier::primary;
}

} // namespace

bool group_selection_order_less(const pending_group      &lhs,
                                const pending_group      &rhs,
                                const candidate_registry &registry) {
  const selection_tier lhs_tier = group_selection_tier(lhs, registry);
  const selection_tier rhs_tier = group_selection_tier(rhs, registry);
  if (lhs_tier != rhs_tier) {
    return lhs_tier < rhs_tier;
  }

  const std::size_t lhs_size = group_span_size(lhs, registry);
  const std::size_t rhs_size = group_span_size(rhs, registry);
  if (lhs_size != rhs_size) {
    return lhs_size > rhs_size;
  }

  return min_group_id(lhs) < min_group_id(rhs);
}

std::vector<candidate_id>
filter_unselected_ids(const std::vector<candidate_id> &ids,
                      const candidate_registry        &registry,
                      const group_selection           &selection) {
  std::vector<candidate_id> out;
  out.reserve(ids.size());

  for (candidate_id id : ids) {
    const move_candidate &candidate = registry.candidate(id);
    if (candidate.role == move_candidate::Role::single_child_wrapper ||
        candidate.role == move_candidate::Role::multi_child_wrapper) {
      continue;
    }
    if (!selection.id_is_used(id) &&
        !selection.candidate_is_suppressed(candidate)) {
      out.push_back(id);
    }
  }

  return out;
}

} // namespace srcmove
