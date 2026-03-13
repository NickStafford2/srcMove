// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file srcdiff_highlight.cpp
 *
 * Highlight moved/changed regions in original.cpp and modified.cpp using
 * srcDiff.
 *
 * Input:
 *   srcdiff_highlight <diff.xml> [original.cpp modified.cpp]
 *
 * If original/modified are omitted, the tool tries to parse them from:
 *   <unit filename="path/to/original.cpp|path/to/modified.cpp">
 *
 * Behavior:
 * - Only uses diff:insert/diff:delete tags that have a move="N" attribute.
 *   This avoids duplicate "wrapper" diff tags.
 * - Extracts raw-ish content from reader.get_current_inner_text().
 * - Locates that text in the target file using whitespace-tolerant matching.
 * - Prints both files with ANSI background highlighting on matched line ranges.
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

static std::string trim(std::string s) {
  auto not_space = [](unsigned char c) { return !std::isspace(c); };
  auto b         = std::find_if(s.begin(), s.end(), not_space);
  auto e         = std::find_if(s.rbegin(), s.rend(), not_space).base();
  if (b >= e)
    return "";
  return std::string(b, e);
}

// Collapse all whitespace runs to a single space, and trim ends.
static std::string normalize_ws(std::string_view in) {
  std::string out;
  out.reserve(in.size());

  bool in_ws = false;
  for (unsigned char c : std::string(in)) {
    if (std::isspace(c)) {
      in_ws = true;
      continue;
    }
    if (in_ws && !out.empty())
      out.push_back(' ');
    in_ws = false;
    out.push_back(static_cast<char>(c));
  }
  return trim(out);
}

static bool read_file_lines(const std::string        &path,
                            std::vector<std::string> &lines) {
  std::ifstream ifs(path);
  if (!ifs)
    return false;

  lines.clear();
  std::string line;
  while (std::getline(ifs, line)) {
    lines.push_back(line);
  }
  return true;
}

struct region {
  diff_kind     kind;
  std::uint32_t move_id;
  std::string   text_raw;  // from get_current_inner_text()
  std::string   text_norm; // normalized for matching
};

// [begin,end] inclusive line range
struct line_range {
  std::size_t begin = 0;
  std::size_t end   = 0;
};

static std::optional<line_range>
find_region_in_lines(const std::vector<std::string> &lines,
                     const std::vector<std::string> &lines_norm,
                     const std::string              &pattern_norm,
                     std::size_t                     max_window_lines = 80) {

  if (pattern_norm.empty())
    return std::nullopt;
  if (lines.empty())
    return std::nullopt;

  // Fast path: single-line contains
  for (std::size_t i = 0; i < lines_norm.size(); ++i) {
    if (lines_norm[i].find(pattern_norm) != std::string::npos) {
      return line_range{i, i};
    }
  }

  // Sliding window join of normalized lines.
  // We build progressively until we either find the pattern or exceed
  // max_window_lines.
  for (std::size_t i = 0; i < lines_norm.size(); ++i) {
    std::string acc;
    acc.reserve(pattern_norm.size() + 64);

    for (std::size_t j = i; j < lines_norm.size() && (j - i) < max_window_lines;
         ++j) {
      if (!acc.empty())
        acc.push_back('\n');
      acc += lines_norm[j];

      if (acc.find(pattern_norm) != std::string::npos) {
        return line_range{i, j};
      }

      // Small heuristic: if acc is already much larger than the pattern,
      // keep going a bit (pattern may cross boundaries), but don't blow up.
      if (acc.size() > pattern_norm.size() + 2000)
        break;
    }
  }

  return std::nullopt;
}

struct highlight_span {
  std::size_t                begin = 0;
  std::size_t                end   = 0;
  std::vector<std::uint32_t> move_ids; // can stack multiple ids on same span
  diff_kind                  kind;
};

// Merge overlapping spans of same kind; also combine move_ids.
static std::vector<highlight_span>
merge_spans(std::vector<highlight_span> spans) {
  if (spans.empty())
    return spans;

  std::sort(spans.begin(), spans.end(), [](const auto &a, const auto &b) {
    if (a.begin != b.begin)
      return a.begin < b.begin;
    return a.end < b.end;
  });

  std::vector<highlight_span> out;
  out.reserve(spans.size());
  out.push_back(spans[0]);

  for (std::size_t i = 1; i < spans.size(); ++i) {
    auto       &cur = out.back();
    const auto &n   = spans[i];

    // Only merge if overlapping AND same kind.
    if (n.kind == cur.kind && n.begin <= cur.end + 1) {
      cur.end = std::max(cur.end, n.end);
      cur.move_ids.insert(cur.move_ids.end(), n.move_ids.begin(),
                          n.move_ids.end());
      std::sort(cur.move_ids.begin(), cur.move_ids.end());
      cur.move_ids.erase(std::unique(cur.move_ids.begin(), cur.move_ids.end()),
                         cur.move_ids.end());
    } else {
      out.push_back(n);
    }
  }

  return out;
}

static bool line_is_in_any_span(std::size_t                        line,
                                const std::vector<highlight_span> &spans,
                                std::size_t &span_index_out) {
  for (std::size_t i = 0; i < spans.size(); ++i) {
    if (line >= spans[i].begin && line <= spans[i].end) {
      span_index_out = i;
      return true;
    }
  }
  return false;
}

// ANSI helpers
static constexpr const char *ANSI_RESET = "\x1b[0m";

// Background colors (truecolor):
// - red-ish for deletes
// - green-ish for inserts
static constexpr const char *BG_DEL = "\x1b[48;2;120;30;30m";
static constexpr const char *BG_INS = "\x1b[48;2;25;90;45m";

// Make move id list as "m=1,7"
static std::string move_ids_label(const std::vector<std::uint32_t> &ids) {
  std::ostringstream oss;
  oss << "m=";
  for (std::size_t i = 0; i < ids.size(); ++i) {
    if (i)
      oss << ",";
    oss << ids[i];
  }
  return oss.str();
}

static void
print_file_with_highlights(const std::string                 &title,
                           const std::string                 &path,
                           const std::vector<std::string>    &lines,
                           const std::vector<highlight_span> &spans) {

  std::cout << "===== " << title << " =====\n";
  std::cout << path << "\n\n";

  // Compute width for line numbers.
  std::size_t width = 1;
  for (std::size_t n = lines.size(); n >= 10; n /= 10)
    ++width;

  for (std::size_t i = 0; i < lines.size(); ++i) {
    std::size_t span_idx = 0;
    const bool  hl       = line_is_in_any_span(i, spans, span_idx);

    std::ostringstream ln;
    ln << (i + 1);
    std::string ln_s = ln.str();
    if (ln_s.size() < width)
      ln_s.insert(0, width - ln_s.size(), ' ');

    if (!hl) {
      std::cout << ln_s << " | " << "     " << " | " << lines[i] << "\n";
      continue;
    }

    const auto       &sp  = spans[span_idx];
    const char       *bg  = (sp.kind == diff_kind::del) ? BG_DEL : BG_INS;
    const std::string tag = move_ids_label(sp.move_ids);

    // Keep the original line raw; only wrap with ANSI background.
    std::cout << ln_s << " | " << tag << " | " << bg << lines[i] << ANSI_RESET
              << "\n";
  }

  std::cout << "\n";
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
    // First pass: parse regions from srcDiff (only move-tagged leaves),
    // and also try to discover original/modified paths from unit@filename.
    srcml_reader reader(diff_xml);

    std::vector<region> regions;
    regions.reserve(128);

    std::string discovered_unit_filename;

    for (const srcml_node &node : reader) {
      if (node.is_start() && node.name == "unit") {
        if (const std::string *f = node.get_attribute_value("filename")) {
          discovered_unit_filename = *f;
        }
      }

      if (!node.is_start())
        continue;

      const std::string fn = node.full_name();
      auto              k  = kind_from_full_name(fn);
      if (!k)
        continue;

      // Only care about the tags that actually represent a move unit:
      // the ones with move="N".
      const std::string *mv = node.get_attribute_value("move");
      if (!mv)
        continue;

      std::uint32_t move_id = 0;
      try {
        move_id = static_cast<std::uint32_t>(std::stoul(*mv));
      } catch (...) {
        continue;
      }

      region r;
      r.kind      = *k;
      r.move_id   = move_id;
      r.text_raw  = reader.get_current_inner_text();
      r.text_norm = normalize_ws(r.text_raw);
      regions.push_back(std::move(r));
    }

    if (argc == 4) {
      original_path = argv[2];
      modified_path = argv[3];
    } else {
      if (!split_unit_filename(discovered_unit_filename, original_path,
                               modified_path)) {
        std::cerr << "error: could not determine original/modified paths from "
                     "unit@filename.\n";
        std::cerr << "pass them explicitly: " << argv[0]
                  << " diff.xml original.cpp modified.cpp\n";
        return 2;
      }
    }

    // Read both files.
    std::vector<std::string> orig_lines, mod_lines;
    if (!read_file_lines(original_path, orig_lines)) {
      std::cerr << "error: failed to read " << original_path << "\n";
      return 3;
    }
    if (!read_file_lines(modified_path, mod_lines)) {
      std::cerr << "error: failed to read " << modified_path << "\n";
      return 4;
    }

    // Pre-normalize file lines (for matching only).
    std::vector<std::string> orig_norm, mod_norm;
    orig_norm.reserve(orig_lines.size());
    mod_norm.reserve(mod_lines.size());
    for (const auto &l : orig_lines)
      orig_norm.push_back(normalize_ws(l));
    for (const auto &l : mod_lines)
      mod_norm.push_back(normalize_ws(l));

    // Find spans for each region.
    std::vector<highlight_span> orig_spans;
    std::vector<highlight_span> mod_spans;

    for (const auto &r : regions) {
      const bool  is_del = (r.kind == diff_kind::del);
      const auto &lines  = is_del ? orig_lines : mod_lines;
      const auto &norms  = is_del ? orig_norm : mod_norm;

      (void)lines; // (raw lines printed later; matching uses norms)
      auto found = find_region_in_lines(
          norms == orig_norm ? orig_lines : mod_lines, norms, r.text_norm);

      // NOTE: That call above mistakenly passes raw lines conditionally; we
      // don't actually use raw lines for matching. To keep it simple and
      // correct, call with the right vectors: We'll just re-run with the
      // correct vectors based on kind.
      if (is_del) {
        found = find_region_in_lines(orig_lines, orig_norm, r.text_norm);
      } else {
        found = find_region_in_lines(mod_lines, mod_norm, r.text_norm);
      }

      if (!found) {
        std::cerr << "warn: could not locate move=" << r.move_id << " ("
                  << (is_del ? "DEL" : "INS") << ") in "
                  << (is_del ? original_path : modified_path) << "\n";
        std::cerr << "      pattern_norm: " << r.text_norm << "\n";
        continue;
      }

      highlight_span sp;
      sp.begin = found->begin;
      sp.end   = found->end;
      sp.kind  = r.kind;
      sp.move_ids.push_back(r.move_id);

      if (is_del)
        orig_spans.push_back(std::move(sp));
      else
        mod_spans.push_back(std::move(sp));
    }

    orig_spans = merge_spans(std::move(orig_spans));
    mod_spans  = merge_spans(std::move(mod_spans));

    print_file_with_highlights("ORIGINAL (deletes highlighted)", original_path,
                               orig_lines, orig_spans);
    print_file_with_highlights("MODIFIED (inserts highlighted)", modified_path,
                               mod_lines, mod_spans);

    return 0;

  } catch (const std::exception &e) {
    std::cerr << "Error: " << e.what() << "\n";
    return 10;
  }
}
