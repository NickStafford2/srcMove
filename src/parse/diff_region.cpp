// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file diff_region.cpp
 *
 * Structure-aware srcDiff parser.
 *
 * Supports:
 *
 * 1) Single-file diff
 *    <unit filename="original.cpp|modified.cpp"> ... </unit>
 *
 * 2) Archive diff
 *    <unit url="orig_dir|mod_dir">
 *      <unit filename="foo.cpp"> ... </unit>
 *      <unit filename="bar.hpp"> ... </unit>
 *    </unit>
 *
 * Important design choice:
 * - detect root mode first
 * - then explicitly read either:
 *     - one file unit
 *     - or an archive containing file units
 *
 * This avoids the "ambient filename stack" approach and better matches
 * srcDiff structure.
 */
#include <cassert>
#include <chrono>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "diff_region.hpp"
#include "move_candidate.hpp"
#include "parse/canonical_subtree.hpp"
#include "profile.hpp"
#include "srcml_node.hpp"

namespace srcmove {

struct open_region_capture {
  std::size_t                      region_id;
  std::vector<captured_srcml_node> nodes;
};

static constexpr std::size_t kNoParent = static_cast<std::size_t>(-1);

using reader_iter = srcml_reader::srcml_reader_iterator;

namespace {

using profile_clock = std::chrono::steady_clock;

struct parse_profile_stats {
  std::uint64_t reader_events = 0;
  std::uint64_t start_events = 0;
  std::uint64_t end_events = 0;
  std::uint64_t text_events = 0;
  std::uint64_t other_events = 0;
  std::uint64_t diff_regions_opened = 0;
  std::uint64_t inner_text_calls = 0;
  double inner_text_ms = 0.0;
  std::uint64_t captured_node_insertions = 0;
  std::uint64_t duplicate_capture_insertions = 0;
  std::uint64_t xpath_calls = 0;
  double xpath_ms = 0.0;
  std::uint64_t exact_canonicalization_calls = 0;
  std::uint64_t exact_canonicalization_nodes = 0;
  double exact_canonicalization_ms = 0.0;
  std::uint64_t normalized_canonicalization_calls = 0;
  std::uint64_t normalized_canonicalization_nodes = 0;
  double normalized_canonicalization_ms = 0.0;
  double temporary_node_copy_ms = 0.0;
};

double elapsed_ms(profile_clock::time_point start) {
  return std::chrono::duration<double, std::milli>(profile_clock::now() - start)
      .count();
}

std::string profiled_xpath(srcml_reader &reader, parse_profile_stats *stats) {
  if (stats == nullptr) {
    return reader.get_current_xpath();
  }
  const auto start = profile_clock::now();
  std::string xpath = reader.get_current_xpath();
  ++stats->xpath_calls;
  stats->xpath_ms += elapsed_ms(start);
  return xpath;
}

void record_captures(parse_profile_stats *stats, std::size_t open_count) {
  if (stats == nullptr || open_count == 0) {
    return;
  }
  stats->captured_node_insertions += open_count;
  stats->duplicate_capture_insertions += open_count - 1;
}

enum class root_mode { single_file, archive };

bool is_unit_start(const srcml_node &node) {
  return node.is_start() && node.name == "unit";
}

bool is_unit_end(const srcml_node &node) {
  return node.is_end() && node.name == "unit";
}

std::optional<move_candidate::Kind>
diff_kind_from_full_name(std::string_view fn) {
  if (fn == "diff:insert") {
    return move_candidate::Kind::insert;
  }
  if (fn == "diff:delete") {
    return move_candidate::Kind::del;
  }
  return std::nullopt;
}

std::string require_filename_attr(const srcml_node &node,
                                  const char       *context_message) {
  const std::string *filename = node.get_attribute_value("filename");
  if (filename == nullptr || filename->empty()) {
    throw std::runtime_error(std::string(context_message) +
                             ": expected unit@filename");
  }
  return *filename;
}

root_mode detect_root_mode(const srcml_node &root_unit) {
  const std::string *filename = root_unit.get_attribute_value("filename");
  return (filename != nullptr) ? root_mode::single_file : root_mode::archive;
}

void open_diff_region(std::vector<diff_region>         &regions,
                      std::vector<open_region_capture> &open_region_stack,
                      const srcml_node                 &node,
                      srcml_reader                     &reader,
                      const std::string                &filename,
                      std::size_t                       node_index,
                      parse_profile_stats              *stats) {
  const auto kind = diff_kind_from_full_name(node.full_name());
  if (!kind) {
    return;
  }

  const std::size_t   parent_id = open_region_stack.empty()
                                      ? kNoParent
                                      : open_region_stack.back().region_id;
  const std::uint32_t depth =
      static_cast<std::uint32_t>(open_region_stack.size());

  if (parent_id != kNoParent) {
    regions[parent_id].has_diff_child = true;
  }

  diff_region region;
  region.kind      = *kind;
  region.filename  = filename;
  region.start_idx   = node_index;
  region.end_idx     = 0;
  region.start_xpath = profiled_xpath(reader, stats);
  if (stats == nullptr) {
    region.raw_text = reader.get_current_inner_text();
  } else {
    const auto start = profile_clock::now();
    region.raw_text = reader.get_current_inner_text();
    ++stats->inner_text_calls;
    stats->inner_text_ms += elapsed_ms(start);
    ++stats->diff_regions_opened;
  }
  region.parent_id   = parent_id;
  region.depth       = depth;

  if (const std::string *mv = node.get_attribute_value("move")) {
    region.pre_marked = true;
    try {
      region.existing_move_id = static_cast<std::uint32_t>(std::stoul(*mv));
    } catch (...) {
      region.existing_move_id = 0;
    }
  }

  regions.push_back(std::move(region));
  open_region_stack.push_back(open_region_capture{regions.size() - 1, {}});
}

void close_diff_region(std::vector<diff_region>         &regions,
                       std::vector<open_region_capture> &open_region_stack,
                       move_candidate::Kind              expected_kind,
                       std::size_t                       node_index,
                       parse_profile_stats              *stats) {
  if (open_region_stack.empty()) {
    throw std::runtime_error("diff end tag without matching diff start tag");
  }

  open_region_capture capture = std::move(open_region_stack.back());
  open_region_stack.pop_back();

  const std::size_t rid = capture.region_id;

  if (regions[rid].kind != expected_kind) {
    throw std::runtime_error("mismatched diff nesting");
  }

  if (regions[rid].end_idx != 0) {
    throw std::runtime_error("diff region was closed more than once");
  }

  regions[rid].end_idx        = node_index;
  regions[rid].captured_nodes = std::move(capture.nodes);

  const auto copy_start = profile_clock::now();
  std::vector<srcml_node> subtree_nodes;
  subtree_nodes.reserve(regions[rid].captured_nodes.size());
  for (const auto &captured : regions[rid].captured_nodes) {
    subtree_nodes.push_back(captured.node);
  }
  if (stats != nullptr) {
    stats->temporary_node_copy_ms += elapsed_ms(copy_start);
  }

  const auto exact_start = profile_clock::now();
  regions[rid].canonical_text = canonicalize_diff_region_subtree(subtree_nodes);
  if (stats != nullptr) {
    stats->exact_canonicalization_ms += elapsed_ms(exact_start);
    ++stats->exact_canonicalization_calls;
    stats->exact_canonicalization_nodes += subtree_nodes.size();
  }
  regions[rid].hash =
      move_candidate::fast_hash_raw(regions[rid].canonical_text);
  canonical_options type2_options;
  type2_options.identifiers        = identifier_normalization::consistent;
  type2_options.normalize_literals = true;
  const auto normalized_start = profile_clock::now();
  canonicalize_diff_region_subtree(subtree_nodes, type2_options,
                                   &regions[rid].type2_normalized_lines,
                                   &regions[rid].type3_normalized_tokens);
  if (stats != nullptr) {
    ++stats->normalized_canonicalization_calls;
    stats->normalized_canonicalization_nodes += subtree_nodes.size();
  }

  canonical_options lexical_options = type2_options;
  lexical_options.ignore_empty_statements = true;
  lexical_options.include_structure = false;
  regions[rid].type2_canonical_text =
      canonicalize_diff_region_subtree(subtree_nodes, lexical_options);
  if (stats != nullptr) {
    stats->normalized_canonicalization_ms += elapsed_ms(normalized_start);
    ++stats->normalized_canonicalization_calls;
    stats->normalized_canonicalization_nodes += subtree_nodes.size();
  }
  regions[rid].type2_hash =
      move_candidate::fast_hash_raw(regions[rid].type2_canonical_text);
}

void advance(reader_iter &it, std::size_t &node_index,
             parse_profile_stats *stats) {
  if (stats != nullptr) {
    ++stats->reader_events;
    if (it->is_start()) {
      ++stats->start_events;
    } else if (it->is_end()) {
      ++stats->end_events;
    } else if (it->is_text()) {
      ++stats->text_events;
    } else {
      ++stats->other_events;
    }
  }
  ++it;
  ++node_index;
}

/**
 * Read one file unit.
 *
 * Entry condition:
 * - *it is the START <unit> for a real file unit
 * - that start node has filename
 *
 * Exit condition:
 * - returns with iterator positioned at the node AFTER the closing </unit>
 *   of that file unit
 */
void read_file_unit(reader_iter              &it,
                    reader_iter              &end,
                    srcml_reader             &reader,
                    const std::string        &filename,
                    std::vector<diff_region> &regions,
                    std::size_t              &node_index,
                    parse_profile_stats      *stats) {
  if (it != end) {
    const srcml_node &start = *it;
    if (!is_unit_start(start)) {
      throw std::runtime_error("read_file_unit: expected file unit start");
    }
  } else {
    throw std::runtime_error("read_file_unit: unexpected end of stream");
  }

  std::vector<open_region_capture> open_region_stack;
  open_region_stack.reserve(32);

  // Consume the starting <unit ...>.
  advance(it, node_index, stats);

  while (it != end) {
    const srcml_node &node      = *it;
    const std::string full_name = node.full_name();

    if (node.is_start()) {
      if (node.name == "unit") {
        throw std::runtime_error("unexpected nested <unit> inside file unit: " +
                                 filename);
      }

      if (const auto kind = diff_kind_from_full_name(full_name)) {
        (void)kind;
        open_diff_region(regions, open_region_stack, node, reader, filename,
                         node_index, stats);
      }

      record_captures(stats, open_region_stack.size());
      for (auto &open_region : open_region_stack) {
        open_region.nodes.push_back(
            captured_srcml_node{node_index, node,
                                profiled_xpath(reader, stats)});
      }

      advance(it, node_index, stats);
      continue;
    }

    if (node.is_end()) {
      record_captures(stats, open_region_stack.size());
      for (auto &open_region : open_region_stack) {
        open_region.nodes.push_back(captured_srcml_node{node_index, node, ""});
      }

      if (const auto kind = diff_kind_from_full_name(full_name)) {
        close_diff_region(regions, open_region_stack, *kind, node_index, stats);
        advance(it, node_index, stats);
        continue;
      }

      if (node.name == "unit") {
        if (!open_region_stack.empty()) {
          throw std::runtime_error(
              "file unit ended before all diff regions were closed: " +
              filename);
        }

        // Consume this file-unit closing tag and return.
        advance(it, node_index, stats);
        return;
      }

      advance(it, node_index, stats);
      continue;
    }

    // TEXT / OTHER
    record_captures(stats, open_region_stack.size());
    for (auto &open_region : open_region_stack) {
      open_region.nodes.push_back(captured_srcml_node{node_index, node, ""});
    }

    advance(it, node_index, stats);
  }

  throw std::runtime_error("unexpected EOF while reading file unit: " +
                           filename);
}

/**
 * Read archive root:
 *   <unit url="..."> <unit filename="..."> ... </unit> ... </unit>
 *
 * Entry condition:
 * - *it is the START root archive unit
 *
 * Exit condition:
 * - returns with iterator positioned after the archive closing </unit>
 */
void read_archive_unit(reader_iter              &it,
                       reader_iter              &end,
                       srcml_reader             &reader,
                       std::vector<diff_region> &regions,
                       std::size_t              &node_index,
                       parse_profile_stats      *stats) {
  if (it != end) {
    const srcml_node &root = *it;
    if (!is_unit_start(root)) {
      throw std::runtime_error("read_archive_unit: expected archive root unit");
    }
    if (detect_root_mode(root) != root_mode::archive) {
      throw std::runtime_error(
          "read_archive_unit called on a single-file root unit");
    }
  } else {
    throw std::runtime_error("read_archive_unit: unexpected end of stream");
  }

  // Consume the archive root start tag.
  advance(it, node_index, stats);

  while (it != end) {
    const srcml_node &node = *it;

    if (node.is_start()) {
      if (node.name != "unit") {
        throw std::runtime_error("unexpected start tag at archive level: " +
                                 node.full_name());
      }

      const std::string filename =
          require_filename_attr(node, "archive child file unit");

      read_file_unit(it, end, reader, filename, regions, node_index, stats);
      continue;
    }

    if (node.is_end()) {
      if (node.name != "unit") {
        throw std::runtime_error("unexpected end tag at archive level: " +
                                 node.full_name());
      }

      // Consume archive closing </unit> and return.
      advance(it, node_index, stats);
      return;
    }

    // Allow text/whitespace between child file units.
    advance(it, node_index, stats);
  }

  throw std::runtime_error("unexpected EOF while reading archive unit");
}

} // namespace

std::vector<diff_region> collect_all_regions(srcml_reader    &reader,
                                             profile_report *profile) {
  std::vector<diff_region> regions;
  regions.reserve(256);
  parse_profile_stats profile_stats;
  parse_profile_stats *stats = profile == nullptr ? nullptr : &profile_stats;

  reader_iter it  = reader.begin();
  reader_iter end = reader.end();

  if (it != end) {
    const srcml_node &root = *it;

    if (!is_unit_start(root)) {
      throw std::runtime_error("expected root <unit> as first node");
    }

    std::size_t node_index = 0;

    switch (detect_root_mode(root)) {
    case root_mode::single_file: {
      const std::string filename =
          require_filename_attr(root, "root single-file unit");
      read_file_unit(it, end, reader, filename, regions, node_index, stats);
      break;
    }

    case root_mode::archive:
      read_archive_unit(it, end, reader, regions, node_index, stats);
      break;
    }

    // We expect the parser to have consumed the whole meaningful structure.
    // Ignore any trailing text/whitespace nodes if the reader yields them.
    while (it != end) {
      advance(it, node_index, stats);
    }

  } else {
    throw std::runtime_error("empty srcDiff document");
  }

#ifndef NDEBUG
  for (const auto &r : regions) {
    assert(r.end_idx != 0 && "diff region never closed");
  }
#endif

  if (profile != nullptr) {
    profile->add_ms("parse.inner_text", profile_stats.inner_text_ms);
    profile->add_ms("parse.xpath", profile_stats.xpath_ms);
    profile->add_ms("parse.exact_canonicalization",
                    profile_stats.exact_canonicalization_ms);
    profile->add_ms("parse.normalized_canonicalization",
                    profile_stats.normalized_canonicalization_ms);
    profile->add_ms("parse.temporary_node_copy",
                    profile_stats.temporary_node_copy_ms);
    profile->add_counter("parse.reader_events", profile_stats.reader_events);
    profile->add_counter("parse.start_events", profile_stats.start_events);
    profile->add_counter("parse.end_events", profile_stats.end_events);
    profile->add_counter("parse.text_events", profile_stats.text_events);
    profile->add_counter("parse.other_events", profile_stats.other_events);
    profile->add_counter("parse.diff_regions_opened",
                         profile_stats.diff_regions_opened);
    profile->add_counter("parse.inner_text_calls",
                         profile_stats.inner_text_calls);
    profile->add_counter("parse.captured_node_insertions",
                         profile_stats.captured_node_insertions);
    profile->add_counter("parse.duplicate_capture_insertions",
                         profile_stats.duplicate_capture_insertions);
    profile->add_counter("parse.xpath_calls", profile_stats.xpath_calls);
    profile->add_counter("parse.exact_canonicalization_calls",
                         profile_stats.exact_canonicalization_calls);
    profile->add_counter("parse.exact_canonicalization_nodes",
                         profile_stats.exact_canonicalization_nodes);
    profile->add_counter("parse.normalized_canonicalization_calls",
                         profile_stats.normalized_canonicalization_calls);
    profile->add_counter("parse.normalized_canonicalization_nodes",
                         profile_stats.normalized_canonicalization_nodes);
  }

  return regions;
}

} // namespace srcmove
