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
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "diff_region.hpp"
#include "move_candidate.hpp"
#include "parse/canonical_subtree.hpp"
#include "srcml_node.hpp"

namespace srcmove {

struct open_region_capture {
  std::size_t region_id;
  std::vector<srcml_node> nodes;
};

static constexpr std::size_t kNoParent = static_cast<std::size_t>(-1);

using reader_iter = srcml_reader::srcml_reader_iterator;

namespace {

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
                                  const char *context_message) {
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

void open_diff_region(std::vector<diff_region> &regions,
                      std::vector<open_region_capture> &open_region_stack,
                      const srcml_node &node, srcml_reader &reader,
                      const std::string &filename, std::size_t node_index) {
  const auto kind = diff_kind_from_full_name(node.full_name());
  if (!kind) {
    return;
  }

  const std::size_t parent_id = open_region_stack.empty()
                                    ? kNoParent
                                    : open_region_stack.back().region_id;
  const std::uint32_t depth =
      static_cast<std::uint32_t>(open_region_stack.size());

  if (parent_id != kNoParent) {
    regions[parent_id].has_diff_child = true;
  }

  diff_region region;
  region.kind = *kind;
  region.filename = filename;
  region.start_idx = node_index;
  region.end_idx = 0;
  region.raw_text = reader.get_current_inner_text();
  region.parent_id = parent_id;
  region.depth = depth;

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

void close_diff_region(std::vector<diff_region> &regions,
                       std::vector<open_region_capture> &open_region_stack,
                       move_candidate::Kind expected_kind,
                       std::size_t node_index) {
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

  regions[rid].end_idx = node_index;
  regions[rid].canonical_text = canonicalize_diff_region_subtree(capture.nodes);
  regions[rid].hash =
      move_candidate::fast_hash_raw(regions[rid].canonical_text);
}

void advance(reader_iter &it, std::size_t &node_index) {
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
void read_file_unit(reader_iter &it, reader_iter &end, srcml_reader &reader,
                    const std::string &filename,
                    std::vector<diff_region> &regions,
                    std::size_t &node_index) {
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
  advance(it, node_index);

  while (it != end) {
    const srcml_node &node = *it;
    const std::string full_name = node.full_name();

    if (node.is_start()) {
      if (node.name == "unit") {
        throw std::runtime_error("unexpected nested <unit> inside file unit: " +
                                 filename);
      }

      if (const auto kind = diff_kind_from_full_name(full_name)) {
        (void)kind;
        open_diff_region(regions, open_region_stack, node, reader, filename,
                         node_index);
      }

      for (auto &open_region : open_region_stack) {
        open_region.nodes.push_back(node);
      }

      advance(it, node_index);
      continue;
    }

    if (node.is_end()) {
      for (auto &open_region : open_region_stack) {
        open_region.nodes.push_back(node);
      }

      if (const auto kind = diff_kind_from_full_name(full_name)) {
        close_diff_region(regions, open_region_stack, *kind, node_index);
        advance(it, node_index);
        continue;
      }

      if (node.name == "unit") {
        if (!open_region_stack.empty()) {
          throw std::runtime_error(
              "file unit ended before all diff regions were closed: " +
              filename);
        }

        // Consume this file-unit closing tag and return.
        advance(it, node_index);
        return;
      }

      advance(it, node_index);
      continue;
    }

    // TEXT / OTHER
    for (auto &open_region : open_region_stack) {
      open_region.nodes.push_back(node);
    }

    advance(it, node_index);
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
void read_archive_unit(reader_iter &it, reader_iter &end, srcml_reader &reader,
                       std::vector<diff_region> &regions,
                       std::size_t &node_index) {
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
  advance(it, node_index);

  while (it != end) {
    const srcml_node &node = *it;

    if (node.is_start()) {
      if (node.name != "unit") {
        throw std::runtime_error("unexpected start tag at archive level: " +
                                 node.full_name());
      }

      const std::string filename =
          require_filename_attr(node, "archive child file unit");

      read_file_unit(it, end, reader, filename, regions, node_index);
      continue;
    }

    if (node.is_end()) {
      if (node.name != "unit") {
        throw std::runtime_error("unexpected end tag at archive level: " +
                                 node.full_name());
      }

      // Consume archive closing </unit> and return.
      advance(it, node_index);
      return;
    }

    // Allow text/whitespace between child file units.
    advance(it, node_index);
  }

  throw std::runtime_error("unexpected EOF while reading archive unit");
}

} // namespace

std::vector<diff_region> collect_all_regions(srcml_reader &reader) {
  std::vector<diff_region> regions;
  regions.reserve(256);

  reader_iter it = reader.begin();
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
      read_file_unit(it, end, reader, filename, regions, node_index);
      break;
    }

    case root_mode::archive:
      read_archive_unit(it, end, reader, regions, node_index);
      break;
    }

    // We expect the parser to have consumed the whole meaningful structure.
    // Ignore any trailing text/whitespace nodes if the reader yields them.
    while (it != end) {
      advance(it, node_index);
    }

  } else {
    throw std::runtime_error("empty srcDiff document");
  }

#ifndef NDEBUG
  for (const auto &r : regions) {
    assert(r.end_idx != 0 && "diff region never closed");
  }
#endif

  return regions;
}

} // namespace srcmove
