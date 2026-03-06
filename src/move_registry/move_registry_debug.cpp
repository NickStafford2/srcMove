// SPDX-License-Identifier: GPL-3.0-only
#include "move_registry_debug.hpp"

#include <algorithm>
#include <cctype>
#include <ostream>
#include <string>
#include <string_view>
#include <unordered_set>
#include <vector>

#include "move_matcher.hpp"

namespace srcmove {
namespace {

template <typename T>
std::string rpad(T value, std::size_t width, char fill = ' ') {
  std::string s;

  if constexpr (std::is_same_v<std::decay_t<T>, std::string>) {
    s = value;
  } else if constexpr (std::is_same_v<std::decay_t<T>, const char *>) {
    s = value;
  } else {
    s = std::to_string(value);
  }

  if (s.size() >= width)
    return s;
  s.append(width - s.size(), fill);
  return s;
}

std::string clean_text(std::string_view s, std::size_t max_len = 60) {
  std::string flattened;
  flattened.reserve(s.size());

  bool prev_space = false;
  for (unsigned char c : s) {
    if (std::isspace(c)) {
      if (!prev_space) {
        flattened.push_back(' ');
      }
      prev_space = true;
    } else {
      flattened.push_back(static_cast<char>(c));
      prev_space = false;
    }
  }

  auto first = flattened.find_first_not_of(' ');
  if (first == std::string::npos) {
    return "";
  }

  auto last = flattened.find_last_not_of(' ');
  std::string out = flattened.substr(first, last - first + 1);

  if (out.size() > max_len) {
    out.resize(max_len);
    out += "...";
  }
  return out;
}

const char *kind_name(move_candidate::Kind kind) {
  return kind == move_candidate::Kind::del ? "DEL" : "INS";
}

const char *group_kind_name(group_kind kind) {
  switch (kind) {
  case group_kind::move_1_to_1:
    return "move_1_to_1";
  case group_kind::moves_many:
    return "moves_many";
  case group_kind::delete_only:
    return "delete_only";
  case group_kind::insert_only:
    return "insert_only";
  case group_kind::copy_or_repeat:
    return "copy_or_repeat";
  case group_kind::ambiguous:
    return "ambiguous";
  }
  return "unknown";
}

void print_candidate_line(const candidate_registry &registry, candidate_id id,
                          std::ostream &os, std::size_t preview_len = 60) {
  const auto &record = registry.record(id);
  const auto &c = record.candidate;

  os << "    " << rpad(id, 5) << " " << rpad(kind_name(c.kind), 4) << " "
     << "[" << c.start_idx << "," << c.end_idx << "] "
     << "active=" << (record.active ? "yes" : "no ") << " "
     << "hash=" << c.hash << " "
     << "file=\"" << c.filename << "\" "
     << "text=\"" << clean_text(c.full_text, preview_len) << "\"\n";
}

struct file_stats {
  std::size_t active = 0;
  std::size_t inactive = 0;
  std::size_t dels = 0;
  std::size_t ins = 0;
};

} // namespace

void print_registry_summary(const candidate_registry &registry,
                            const content_groups &groups, std::ostream &os) {
  os << "candidate_registry:\n";
  os << "  files: " << registry.file_count() << "\n";
  os << "  total records: " << registry.total_record_count() << "\n";
  os << "  active candidates: " << registry.active_candidate_count() << "\n";
  os << "  inactive candidates: "
     << (registry.total_record_count() - registry.active_candidate_count())
     << "\n";
  os << "  hash buckets: " << registry.bucket_count() << "\n";
  os << "  content groups: " << groups.group_count() << "\n";

  std::size_t move11 = 0;
  std::size_t many = 0;
  std::size_t delonly = 0;
  std::size_t inonly = 0;
  std::size_t copy = 0;
  std::size_t amb = 0;

  std::size_t total_group_del_ids = 0;
  std::size_t total_group_ins_ids = 0;

  for (const auto &g : groups.groups()) {
    total_group_del_ids += g.del_count();
    total_group_ins_ids += g.ins_count();

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

  os << "  grouped ids:\n";
  os << "    delete ids: " << total_group_del_ids << "\n";
  os << "    insert ids: " << total_group_ins_ids << "\n";

  os << "  group kinds:\n";
  os << "    move_1_to_1: " << move11 << "\n";
  os << "    moves_many: " << many << "\n";
  os << "    delete_only: " << delonly << "\n";
  os << "    insert_only: " << inonly << "\n";
  os << "    copy_or_repeat: " << copy << "\n";
  os << "    ambiguous: " << amb << "\n";
}

void print_registry_by_file(const candidate_registry &registry,
                            std::ostream &os) {
  os << "\n=== REGISTRY BY FILE ===\n";

  std::unordered_set<std::string> seen_files;
  seen_files.reserve(registry.file_count());

  for (const auto &record : registry.records()) {
    seen_files.insert(record.candidate.filename);
  }

  std::vector<std::string> files(seen_files.begin(), seen_files.end());
  std::sort(files.begin(), files.end());

  for (const auto &file : files) {
    file_stats stats;

    const auto *ids = registry.file_candidate_ids(file);
    if (ids == nullptr) {
      os << "file: " << file << " (no tracked ids)\n";
      continue;
    }

    for (candidate_id id : *ids) {
      const auto &rec = registry.record(id);
      if (rec.active) {
        ++stats.active;
      } else {
        ++stats.inactive;
      }

      if (rec.candidate.kind == move_candidate::Kind::del) {
        ++stats.dels;
      } else {
        ++stats.ins;
      }
    }

    os << "file: " << file << "\n";
    os << "  ids: " << ids->size() << "  active: " << stats.active
       << "  inactive: " << stats.inactive << "  dels: " << stats.dels
       << "  ins: " << stats.ins << "\n";
  }
}

void print_hash_buckets(const candidate_registry &registry, std::ostream &os,
                        std::size_t max_buckets, std::size_t preview_per_side) {
  os << "\n=== HASH BUCKETS ===\n";

  struct bucket_view {
    std::uint64_t hash = 0;
    const bucket_ids *bucket = nullptr;
  };

  std::vector<bucket_view> ordered;
  ordered.reserve(registry.hash_buckets().size());

  for (const auto &kv : registry.hash_buckets()) {
    ordered.push_back(bucket_view{kv.first, &kv.second});
  }

  std::sort(ordered.begin(), ordered.end(),
            [](const bucket_view &a, const bucket_view &b) {
              const std::size_t asz =
                  a.bucket->del_ids.size() + a.bucket->ins_ids.size();
              const std::size_t bsz =
                  b.bucket->del_ids.size() + b.bucket->ins_ids.size();
              if (asz != bsz)
                return asz > bsz;
              return a.hash < b.hash;
            });

  const std::size_t n = std::min(max_buckets, ordered.size());
  for (std::size_t bi = 0; bi < n; ++bi) {
    const auto &view = ordered[bi];
    const auto &bucket = *view.bucket;

    os << "bucket[" << bi << "]"
       << " hash=" << view.hash << " dels=" << bucket.del_ids.size()
       << " ins=" << bucket.ins_ids.size() << "\n";

    const std::size_t del_preview =
        std::min(preview_per_side, bucket.del_ids.size());
    for (std::size_t i = 0; i < del_preview; ++i) {
      print_candidate_line(registry, bucket.del_ids[i], os);
    }
    if (bucket.del_ids.size() > del_preview) {
      os << "    ... " << (bucket.del_ids.size() - del_preview)
         << " more delete candidates\n";
    }

    const std::size_t ins_preview =
        std::min(preview_per_side, bucket.ins_ids.size());
    for (std::size_t i = 0; i < ins_preview; ++i) {
      print_candidate_line(registry, bucket.ins_ids[i], os);
    }
    if (bucket.ins_ids.size() > ins_preview) {
      os << "    ... " << (bucket.ins_ids.size() - ins_preview)
         << " more insert candidates\n";
    }
  }

  if (ordered.size() > n) {
    os << "... " << (ordered.size() - n) << " more buckets not shown\n";
  }
}

void print_content_groups(const candidate_registry &registry,
                          const content_groups &groups, std::ostream &os,
                          std::size_t max_groups,
                          std::size_t preview_per_side) {
  os << "\n=== CONTENT GROUPS ===\n";

  const std::size_t n = std::min(max_groups, groups.group_count());
  for (std::size_t gi = 0; gi < n; ++gi) {
    const auto &g = groups.groups()[gi];
    const auto del_ids = groups.delete_ids(g);
    const auto ins_ids = groups.insert_ids(g);

    os << "group[" << gi << "]"
       << " id=" << g.group_id << " hash=" << g.content_hash
       << " kind=" << group_kind_name(g.kind) << " dels=" << del_ids.size()
       << " ins=" << ins_ids.size() << "\n";

    const std::size_t del_preview = std::min(preview_per_side, del_ids.size());
    for (std::size_t i = 0; i < del_preview; ++i) {
      print_candidate_line(registry, del_ids[i], os);
    }
    if (del_ids.size() > del_preview) {
      os << "    ... " << (del_ids.size() - del_preview)
         << " more delete candidates\n";
    }

    const std::size_t ins_preview = std::min(preview_per_side, ins_ids.size());
    for (std::size_t i = 0; i < ins_preview; ++i) {
      print_candidate_line(registry, ins_ids[i], os);
    }
    if (ins_ids.size() > ins_preview) {
      os << "    ... " << (ins_ids.size() - ins_preview)
         << " more insert candidates\n";
    }
  }

  if (groups.group_count() > n) {
    os << "... " << (groups.group_count() - n) << " more groups not shown\n";
  }
}

void print_greedy_matches(const candidate_registry &registry,
                          const content_groups &groups, std::ostream &os) {
  print_registry_summary(registry, groups, os);

  const auto matches = greedy_match_1_to_1(groups);

  std::unordered_set<candidate_id> matched_del_ids;
  std::unordered_set<candidate_id> matched_ins_ids;
  matched_del_ids.reserve(matches.size());
  matched_ins_ids.reserve(matches.size());

  os << "\n=== GREEDY MATCHES (DEL -> INS) ===\n";
  for (const auto &m : matches) {
    matched_del_ids.insert(m.del_id);
    matched_ins_ids.insert(m.ins_id);

    const auto &d = registry.candidate(m.del_id);
    const auto &ins = registry.candidate(m.ins_id);

    os << "DEL [" << d.start_idx << "," << d.end_idx << "] " << d.filename
       << " -> "
       << "INS [" << ins.start_idx << "," << ins.end_idx << "] " << ins.filename
       << " hash=" << d.hash << " chars(del)=" << d.full_text.size()
       << " chars(ins)=" << ins.full_text.size() << " del_text=\""
       << clean_text(d.full_text, 40) << "\""
       << " ins_text=\"" << clean_text(ins.full_text, 40) << "\""
       << "\n";
  }

  os << "\n=== UNMATCHED ACTIVE CANDIDATES ===\n";
  for (candidate_id id = 0;
       id < static_cast<candidate_id>(registry.total_record_count()); ++id) {
    if (!registry.is_active(id)) {
      continue;
    }

    const auto &c = registry.candidate(id);
    if (c.kind == move_candidate::Kind::del) {
      if (matched_del_ids.find(id) == matched_del_ids.end()) {
        print_candidate_line(registry, id, os);
      }
    } else {
      if (matched_ins_ids.find(id) == matched_ins_ids.end()) {
        print_candidate_line(registry, id, os);
      }
    }
  }
}

void print_full_registry_debug(const candidate_registry &registry,
                               const content_groups &groups, std::ostream &os,
                               std::size_t max_buckets, std::size_t max_groups,
                               std::size_t preview_per_side) {
  print_registry_summary(registry, groups, os);
  print_registry_by_file(registry, os);
  print_hash_buckets(registry, os, max_buckets, preview_per_side);
  print_content_groups(registry, groups, os, max_groups, preview_per_side);
  print_greedy_matches(registry, groups, os);
}

} // namespace srcmove
