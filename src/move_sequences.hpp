// SPDX-License-Identifier: GPL-3.0-only
#ifndef INCLUDED_SRCMOVE_MOVE_SEQUENCES_HPP
#define INCLUDED_SRCMOVE_MOVE_SEQUENCES_HPP

#include <cstddef>
#include <string>
#include <vector>

namespace srcmove {

class candidate_registry;
class content_groups;
struct move_entry;

struct move_sequence_endpoint {
  std::string revision_file;
  std::string parent_id;
  std::size_t first_child_ordinal = 0;
  std::size_t last_child_ordinal = 0;
  std::vector<std::string> member_xpaths;
};

// An ordered reporting unit, not a content-equivalence group or editing event.
// Members remain ordinary selected moves with their original XML annotations.
struct move_sequence {
  std::string sequence_id;
  std::vector<std::string> member_move_ids;
  move_sequence_endpoint from;
  move_sequence_endpoint to;
};

// Aggregate only selected unique Type-1 structural-child correspondences.
// Expected O(groups + moves log moves), with no new content-pair comparisons.
std::vector<move_sequence>
build_move_sequences(const candidate_registry &registry,
                     const content_groups &groups,
                     const std::vector<move_entry> &moves);

} // namespace srcmove
#endif
