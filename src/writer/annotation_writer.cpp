// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file annotation_writer.cpp
 *
 * Writes the annotated srcDiff document by copying the input stream and
 * patching move-related attributes onto selected start tags.
 */
#include <cctype>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <string>
#include <system_error>
#include <unordered_map>
#include <vector>

// uncomment to disable assert()
// #define NDEBUG
#include <cassert>

#include "annotation_plan.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_groups.hpp"
#include "parse/diff_region.hpp"
#include "profile.hpp"
#include "srcml_node.hpp"
#include "srcml_reader.hpp"
#include "srcml_writer.hpp"
#include "summary.hpp"

namespace srcmove {

namespace {

using profile_clock = std::chrono::steady_clock;

struct annotation_profile_stats {
  std::uint64_t reader_events = 0;
  std::uint64_t start_events = 0;
  std::uint64_t end_events = 0;
  std::uint64_t text_events = 0;
  std::uint64_t other_events = 0;
  std::uint64_t nodes_written = 0;
  std::uint64_t tagged_nodes = 0;
  std::uint64_t unmodified_nodes = 0;
  std::uint64_t xpath_requests = 0;
  double copy_unmodified_ms = 0.0;
  double patch_tagged_ms = 0.0;
  double patch_root_ms = 0.0;
};

double elapsed_ms(profile_clock::time_point start) {
  return std::chrono::duration<double, std::milli>(profile_clock::now() - start)
      .count();
}

constexpr const char *kMvNamespaceUri = "http://www.srcML.org/srcMove";
constexpr const char *kMvXmlnsAttr    = "xmlns:mv";
constexpr const char *kMvMoveAttr     = "mv:id";
constexpr const char *kMvFromAttr     = "mv:from";
constexpr const char *kMvToAttr       = "mv:to";

bool is_root_unit_start(const srcml_node &node, std::size_t index) {
  return index == 0 && node.is_start() && node.name == "unit";
}

const std::string *get_existing_move_attr(const srcml_node &node) {
  if (const std::string *mv = node.get_attribute_value(kMvMoveAttr)) {
    return mv;
  }
  return node.get_attribute_value("move");
}

srcml_node patch_root_unit_namespace(const srcml_node &node) {
  srcml_node patched = node;

  // Only add it if it is not already present.
  if (patched.get_attribute_value(kMvXmlnsAttr) == nullptr) {
    patched.set_attribute(kMvXmlnsAttr, kMvNamespaceUri);
  }

  return patched;
}

std::string join_xpath_union(const std::vector<std::string> &values) {
  std::string out;
  for (std::size_t i = 0; i < values.size(); ++i) {
    if (i != 0)
      out += " | ";
    out += values[i];
  }
  return out;
}

std::unordered_map<std::string, move_entry>
write_with_move_annotations(const std::string &in_filename,
                            const std::string &out_filename,
                            const tag_map     &tags,
                            profile_report    *profile) {
  scoped_profile_timer timer(profile, "annotation.write_stream");
  std::unordered_map<std::string, move_entry> moves;
  annotation_profile_stats stats;

  {
    srcml_reader reader(in_filename);
    srcml_writer writer(out_filename);

    // O(input XML nodes + tagged regions). Untagged nodes are copied through;
    // tagged START nodes also patch attributes and collect move summary entries.
    std::size_t i = 0;
    for (const srcml_node &node : reader) {
      if (profile != nullptr) {
        ++stats.reader_events;
        if (node.is_start()) {
          ++stats.start_events;
        } else if (node.is_end()) {
          ++stats.end_events;
        } else if (node.is_text()) {
          ++stats.text_events;
        } else {
          ++stats.other_events;
        }
      }

      if (is_root_unit_start(node, i)) {
        const auto start = profile_clock::now();
        writer.write(patch_root_unit_namespace(node));
        if (profile != nullptr) {
          stats.patch_root_ms += elapsed_ms(start);
          ++stats.nodes_written;
        }
        ++i;
        continue;
      }

      if (node.is_start()) {
        auto it = tags.find(i);
        if (it != tags.end()) {
          const auto start = profile_clock::now();
          srcml_node        patched = node;
          const std::string xpath   = reader.get_current_xpath();
          const move_tag    &tag      = it->second;
          const std::string &move_id  = tag.move_id;
          const std::string &raw_text = tag.raw_text;

          patched.set_attribute(kMvMoveAttr, move_id);

          if (!tag.partner_xpaths.empty()) {
            const std::string joined = join_xpath_union(tag.partner_xpaths);

            if (tag.kind == move_candidate::Kind::del) {
              patched.set_attribute(kMvToAttr, joined);
            } else {
              patched.set_attribute(kMvFromAttr, joined);
            }
          }

          writer.write(patched);

          move_entry &entry = moves[move_id];
          entry.move_id     = move_id;
          entry.match_kind  = tag.match_kind;

          if (tag.kind == move_candidate::Kind::del) {
            entry.from_xpaths.push_back(xpath);
            entry.from_raw_texts.push_back(raw_text);
          } else {
            entry.to_xpaths.push_back(xpath);
            entry.to_raw_texts.push_back(raw_text);
          }

          if (profile != nullptr) {
            stats.patch_tagged_ms += elapsed_ms(start);
            ++stats.nodes_written;
            ++stats.tagged_nodes;
            ++stats.xpath_requests;
          }
          ++i;
          continue;
        }
      }

      const auto start = profile_clock::now();
      writer.write(node);
      if (profile != nullptr) {
        stats.copy_unmodified_ms += elapsed_ms(start);
        ++stats.nodes_written;
        ++stats.unmodified_nodes;
      }
      ++i;
    }
  }

  if (profile != nullptr) {
    profile->add_ms("annotation.copy_unmodified", stats.copy_unmodified_ms);
    profile->add_ms("annotation.patch_tagged", stats.patch_tagged_ms);
    profile->add_ms("annotation.patch_root", stats.patch_root_ms);
    profile->add_counter("annotation.reader_events", stats.reader_events);
    profile->add_counter("annotation.start_events", stats.start_events);
    profile->add_counter("annotation.end_events", stats.end_events);
    profile->add_counter("annotation.text_events", stats.text_events);
    profile->add_counter("annotation.other_events", stats.other_events);
    profile->add_counter("annotation.nodes_written", stats.nodes_written);
    profile->add_counter("annotation.tagged_nodes", stats.tagged_nodes);
    profile->add_counter("annotation.unmodified_nodes",
                         stats.unmodified_nodes);
    profile->add_counter("annotation.xpath_requests", stats.xpath_requests);

    std::error_code error;
    const auto input_bytes = std::filesystem::file_size(in_filename, error);
    if (!error) {
      profile->add_counter("annotation.bytes_read", input_bytes);
    }
    error.clear();
    const auto output_bytes = std::filesystem::file_size(out_filename, error);
    if (!error) {
      profile->add_counter("annotation.bytes_written", output_bytes);
    }
  }

  return moves;
}

} // namespace

std::vector<move_entry> annotate(const std::vector<diff_region> &regions,
                                 const candidate_registry       &registry,
                                 const content_groups           &groups,
                                 const std::string &srcdiff_in_filename,
                                 const std::string &srcdiff_out_filename,
                                 profile_report    *profile) {

  scoped_profile_timer total_timer(profile, "annotation.total");

  const tag_map tags =
      build_move_tags(groups, registry, srcdiff_in_filename, profile);

  // second pass
  auto moves_map = write_with_move_annotations(srcdiff_in_filename,
                                               srcdiff_out_filename, tags,
                                               profile);
  std::vector<move_entry> moves;

  {
    scoped_profile_timer timer(profile, "annotation.materialize_moves");
    moves.reserve(moves_map.size());
    // O(move groups). Converts the writer's move-id keyed map into summary
    // entries consumed by the pipeline result.
    for (auto &kv : moves_map)
      moves.push_back(std::move(kv.second));
  }

  return moves;
}

} // namespace srcmove
