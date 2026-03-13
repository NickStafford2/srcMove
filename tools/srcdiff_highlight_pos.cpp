// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file srcdiff_highlight_pos.cpp
 *
 * Highlight changed regions in original.cpp and modified.cpp using srcDiff
 * --position.
 *
 * Strategy:
 * - Stream srcDiff XML with srcml_reader
 * - When encountering <diff:insert> or <diff:delete>, enter "in_diff" mode
 * - While in_diff, find the first descendant element that has pos:start and
 * pos:end (these attributes come from --position)
 * - Record that range:
 *     delete -> original file
 *     insert -> modified file
 * - Print files with ANSI background highlights by line/column spans
 *
 * Usage:
 *   srcdiff_highlight_pos <diff.xml> [original.cpp modified.cpp]
 *
 * Notes:
 * - Columns in pos:start/end are 1-based.
 * - We treat pos:end as inclusive (common in srcML position reporting).
 * - Tabs: srcDiff includes pos:tabs, but the pos columns are already "tab
 * aware" according to srcML's tabstop setting. We highlight by raw byte columns
 * in the source line; for tabs, this may not perfectly match terminal visual
 * columns.
 */

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "srcml_node.hpp"
#include "srcml_reader.hpp"

namespace {

enum class diff_kind { insert, del };

static std::optional<diff_kind> kind_from_full_name(std::string_view fn) {
  if (fn == "diff:insert")
    return diff_kind::insert;
  if (fn == "diff:delete")
    return diff_kind::del;
  return std::nullopt;
}

static const char *kind_label(diff_kind k) {
  return (k == diff_kind::insert) ? "INS" : "DEL";
}

static bool split_unit_filename(const std::string &unit_filename,
                                std::string       &orig_out,
                                std::string       &mod_out) {
  auto pos = unit_filename.find('|');
  if (pos == std::string::npos)
    return false;
  orig_out = unit_filename.substr(0, pos);
  mod_out  = unit_filename.substr(pos + 1);
  return true;
}

static bool read_lines(const std::string &path, std::vector<std::string> &out) {
  std::ifstream ifs(path);
  if (!ifs)
    return false;
  out.clear();
  std::string line;
  while (std::getline(ifs, line)) {
    // keep line without '\n'
    if (!line.empty() && line.back() == '\r')
      line.pop_back();
    out.push_back(line);
  }
  // If file ends with trailing newline, getline drops it; that's fine.
  return true;
}

// pos "L:C"
struct pos_point {
  std::size_t line = 0; // 1-based
  std::size_t col  = 0; // 1-based
};

static std::optional<pos_point> parse_pos_point(const std::string &s) {
  auto p = s.find(':');
  if (p == std::string::npos)
    return std::nullopt;
  try {
    std::size_t L = static_cast<std::size_t>(std::stoul(s.substr(0, p)));
    std::size_t C = static_cast<std::size_t>(std::stoul(s.substr(p + 1)));
    if (L == 0 || C == 0)
      return std::nullopt;
    return pos_point{L, C};
  } catch (...) {
    return std::nullopt;
  }
}

struct range {
  diff_kind kind;
  pos_point start;
  pos_point end; // inclusive
};

// ANSI background colors
static constexpr const char *ANSI_RESET = "\x1b[0m";
static constexpr const char *BG_DEL     = "\x1b[48;2;120;30;30m";
static constexpr const char *BG_INS     = "\x1b[48;2;25;90;45m";

static const char *bg_for_kind(diff_kind k) {
  return (k == diff_kind::del) ? BG_DEL : BG_INS;
}

// Clamp [a,b] to [lo,hi], inclusive; return empty if no overlap.
static std::optional<std::pair<std::size_t, std::size_t>>
clamp_inclusive(std::size_t a, std::size_t b, std::size_t lo, std::size_t hi) {
  if (a > b)
    std::swap(a, b);
  std::size_t x = std::max(a, lo);
  std::size_t y = std::min(b, hi);
  if (x > y)
    return std::nullopt;
  return std::pair{x, y};
}

static void print_file_highlighted(const std::string              &title,
                                   const std::string              &path,
                                   const std::vector<std::string> &lines,
                                   const std::vector<range>       &ranges,
                                   diff_kind                       which_kind) {
  std::cout << "===== " << title << " =====\n";
  std::cout << path << "\n\n";

  // compute width for line numbers
  std::size_t width = 1;
  for (std::size_t n = lines.size(); n >= 10; n /= 10)
    ++width;

  // For quick filtering
  std::vector<range> rs;
  rs.reserve(ranges.size());
  for (const auto &r : ranges) {
    if (r.kind == which_kind)
      rs.push_back(r);
  }

  for (std::size_t i = 0; i < lines.size(); ++i) {
    const std::size_t line_no = i + 1;
    const auto       &line    = lines[i];

    std::ostringstream ln;
    ln << line_no;
    std::string ln_s = ln.str();
    if (ln_s.size() < width)
      ln_s.insert(0, width - ln_s.size(), ' ');

    // Build segments to highlight on this line (1-based columns).
    struct seg {
      std::size_t b; // 1-based inclusive
      std::size_t e; // 1-based inclusive
    };
    std::vector<seg> segs;

    for (const auto &r : rs) {
      if (line_no < r.start.line || line_no > r.end.line)
        continue;

      std::size_t b = 1;
      std::size_t e = line.size() == 0 ? 1 : line.size();

      if (r.start.line == line_no)
        b = r.start.col;
      if (r.end.line == line_no)
        e = r.end.col;

      // clamp to the line length in bytes/characters (simple model)
      const std::size_t hi = (line.size() == 0) ? 1 : line.size();
      auto              cl = clamp_inclusive(b, e, 1, hi);
      if (cl)
        segs.push_back(seg{cl->first, cl->second});
    }

    std::sort(segs.begin(), segs.end(),
              [](const seg &a, const seg &b) { return a.b < b.b; });

    // Merge overlaps
    std::vector<seg> merged;
    for (const auto &s : segs) {
      if (merged.empty() || s.b > merged.back().e + 1) {
        merged.push_back(s);
      } else {
        merged.back().e = std::max(merged.back().e, s.e);
      }
    }

    std::cout << ln_s << " | ";

    if (merged.empty()) {
      std::cout << line << "\n";
      continue;
    }

    const char *bg = bg_for_kind(which_kind);

    // Print with highlights (convert 1-based columns to 0-based indices)
    std::size_t cursor = 1;
    for (const auto &s : merged) {
      if (cursor < s.b) {
        std::cout.write(line.data() + static_cast<std::ptrdiff_t>(cursor - 1),
                        static_cast<std::streamsize>(s.b - cursor));
      }
      std::cout << bg;
      std::cout.write(line.data() + static_cast<std::ptrdiff_t>(s.b - 1),
                      static_cast<std::streamsize>(s.e - s.b + 1));
      std::cout << ANSI_RESET;
      cursor = s.e + 1;
    }
    // trailing
    if (cursor <= line.size()) {
      std::cout.write(line.data() + static_cast<std::ptrdiff_t>(cursor - 1),
                      static_cast<std::streamsize>(line.size() - (cursor - 1)));
    }
    std::cout << "\n";
  }

  std::cout << "\n";
}

} // namespace

int main(int argc, char **argv) {
  if (argc != 2 && argc != 4) {
    std::cerr << "usage: " << argv[0]
              << " <diff.xml> [original.cpp modified.cpp]\n";
    return 1;
  }

  const std::string diff_xml = argv[1];

  std::string original_path;
  std::string modified_path;

  try {
    srcml_reader reader(diff_xml);

    std::string        unit_filename_attr;
    std::vector<range> ranges;
    ranges.reserve(128);

    // Track whether we're currently inside a diff region, and whether we've
    // already captured a pos range for it.
    struct diff_frame {
      diff_kind kind;
      bool      captured = false;
    };
    std::vector<diff_frame> stack;
    stack.reserve(64);

    for (const srcml_node &node : reader) {
      if (node.is_start() && node.name == "unit") {
        if (const std::string *f = node.get_attribute_value("filename"))
          unit_filename_attr = *f;
      }

      const auto k = kind_from_full_name(node.full_name());

      if (node.is_start() && k) {
        stack.push_back(diff_frame{*k, false});
        continue;
      }

      // While inside diff region, look for the first element with
      // pos:start/end.
      if (node.is_start() && !stack.empty() && !stack.back().captured) {
        const std::string *ps = node.get_attribute_value("pos:start");
        const std::string *pe = node.get_attribute_value("pos:end");
        if (ps && pe) {
          auto s = parse_pos_point(*ps);
          auto e = parse_pos_point(*pe);
          if (s && e) {
            ranges.push_back(range{stack.back().kind, *s, *e});
            stack.back().captured = true;
          }
        }
      }

      if (node.is_end() && k) {
        if (stack.empty()) {
          std::cerr << "error: diff end without start\n";
          return 2;
        }
        // pop one frame per end tag
        stack.pop_back();
      }
    }

    if (!stack.empty()) {
      std::cerr << "error: unclosed diff region(s)\n";
      return 3;
    }

    if (argc == 4) {
      original_path = argv[2];
      modified_path = argv[3];
    } else {
      if (!split_unit_filename(unit_filename_attr, original_path,
                               modified_path)) {
        std::cerr << "error: could not parse unit@filename to get "
                     "original|modified.\n";
        std::cerr << "pass paths explicitly: " << argv[0]
                  << " diff.xml original.cpp modified.cpp\n";
        return 4;
      }
    }

    std::vector<std::string> orig_lines, mod_lines;
    if (!read_lines(original_path, orig_lines)) {
      std::cerr << "error: failed to read " << original_path << "\n";
      return 5;
    }
    if (!read_lines(modified_path, mod_lines)) {
      std::cerr << "error: failed to read " << modified_path << "\n";
      return 6;
    }

    print_file_highlighted("ORIGINAL (deletes highlighted)", original_path,
                           orig_lines, ranges, diff_kind::del);
    print_file_highlighted("MODIFIED (inserts highlighted)", modified_path,
                           mod_lines, ranges, diff_kind::insert);

    return 0;

  } catch (const std::exception &e) {
    std::cerr << "Error: " << e.what() << "\n";
    return 10;
  }
}
