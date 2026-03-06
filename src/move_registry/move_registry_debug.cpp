// SPDX-License-Identifier: GPL-3.0-only
#include "move_registry_debug.hpp"

#include <ostream>

#include "move_matcher.hpp"
#include "move_registry.hpp"

namespace srcmove {

void print_registry_summary(const move_registry &mr, std::ostream &os) {
  os << "move_registry:\n";
  os << "  deletes: " << mr.delete_count() << "\n";
  os << "  inserts: " << mr.insert_count() << "\n";
  os << "  hash buckets: " << mr.bucket_count() << "\n";
  os << "  content groups: " << mr.group_count() << "\n";

  std::size_t move11 = 0, many = 0, delonly = 0, inonly = 0, copy = 0, amb = 0;
  for (const auto &g : mr.groups()) {
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

void print_greedy_matches(const move_registry &mr, std::ostream &os) {
  print_registry_summary(mr, os);

  const auto matches = greedy_match_1_to_1(mr);

  const auto &dels = mr.deletes();
  const auto &inss = mr.inserts();

  os << "\n=== GREEDY MATCHES (DEL -> INS) ===\n";
  for (const auto &m : matches) {
    const auto &d = dels[m.del_id];
    const auto &ins = inss[m.ins_id];

    os << "DEL [" << d.start_idx << "," << d.end_idx << "] " << d.filename
       << "  ->  "
       << "INS [" << ins.start_idx << "," << ins.end_idx << "] " << ins.filename
       << "  hash=" << d.hash << "  chars(del)=" << d.full_text.size()
       << "  chars(ins)=" << ins.full_text.size() << "\n";
  }
}

} // namespace srcmove
