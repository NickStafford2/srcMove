// SPDX-License-Identifier: GPL-3.0-only
#include "move_registry_debug.hpp"

#include <ostream>

#include "move_matcher.hpp"

namespace srcmove {

void print_registry_summary(const candidate_registry &registry,
                            const content_groups &groups, std::ostream &os) {
  os << "candidate_registry:\n";
  os << "  files: " << registry.file_count() << "\n";
  os << "  total records: " << registry.total_record_count() << "\n";
  os << "  active candidates: " << registry.active_candidate_count() << "\n";
  os << "  hash buckets: " << registry.bucket_count() << "\n";
  os << "  content groups: " << groups.group_count() << "\n";

  std::size_t move11 = 0;
  std::size_t many = 0;
  std::size_t delonly = 0;
  std::size_t inonly = 0;
  std::size_t copy = 0;
  std::size_t amb = 0;

  for (const auto &g : groups.groups()) {
    switch (g.kind) {
    case group_kind::move_1_to_1:
      ++move11;
      break;
    case group_kind::moves_many:
      ++many;
      break;
    case group_kind::delete_only:
      ++delonly;
      break;
    case group_kind::insert_only:
      ++inonly;
      break;
    case group_kind::copy_or_repeat:
      ++copy;
      break;
    case group_kind::ambiguous:
      ++amb;
      break;
    }
  }

  os << "  group kinds:\n";
  os << "    move_1_to_1: " << move11 << "\n";
  os << "    moves_many: " << many << "\n";
  os << "    delete_only: " << delonly << "\n";
  os << "    insert_only: " << inonly << "\n";
  os << "    copy_or_repeat: " << copy << "\n";
  os << "    ambiguous: " << amb << "\n";
}

void print_greedy_matches(const candidate_registry &registry,
                          const content_groups &groups, std::ostream &os) {
  print_registry_summary(registry, groups, os);

  const auto matches = greedy_match_1_to_1(groups);

  os << "\n=== GREEDY MATCHES (DEL -> INS) ===\n";
  for (const auto &m : matches) {
    const auto &d = registry.candidate(m.del_id);
    const auto &ins = registry.candidate(m.ins_id);

    os << "DEL [" << d.start_idx << "," << d.end_idx << "] " << d.filename
       << "  ->  "
       << "INS [" << ins.start_idx << "," << ins.end_idx << "] " << ins.filename
       << "  hash=" << d.hash << "  chars(del)=" << d.full_text.size()
       << "  chars(ins)=" << ins.full_text.size() << "\n";
  }
}

} // namespace srcmove
