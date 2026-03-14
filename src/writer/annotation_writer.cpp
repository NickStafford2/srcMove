// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file annotation_writer.cpp
 *
 * Writes the annotated srcDiff document by copying the input stream and
 * patching move-related attributes onto diff start tags.
 */
#include <cctype>
#include <string>
#include <unordered_map>
#include <vector>

// uncomment to disable assert()
// #define NDEBUG
#include <cassert>

#include "annotation_plan.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/content_groups.hpp"
#include "parse/diff_region.hpp"
#include "srcml_node.hpp"
#include "srcml_reader.hpp"
#include "srcml_writer.hpp"
#include "summary.hpp"

namespace srcmove {

namespace {

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
                            const tag_map     &tags) {

  srcml_reader reader(in_filename);
  srcml_writer writer(out_filename);

  std::unordered_map<std::string, move_entry> moves;

  std::size_t i = 0;
  for (const srcml_node &node : reader) {
    if (is_root_unit_start(node, i)) {
      writer.write(patch_root_unit_namespace(node));
      ++i;
      continue;
    }

    if (node.is_start()) {
      const std::string fn = node.full_name();

      if (fn == "diff:insert" || fn == "diff:delete") {
        srcml_node        patched = node;
        const std::string xpath   = reader.get_current_xpath();

        if (const std::string *existing_move = get_existing_move_attr(node)) {
          writer.write(patched);

          const std::string &move_id = *existing_move;

          move_entry &entry = moves[move_id];
          entry.move_id     = move_id;

          if (fn == "diff:delete") {
            entry.from_xpaths.push_back(xpath);
          } else {
            entry.to_xpaths.push_back(xpath);
          }

          ++i;
          continue;
        }

        auto it = tags.find(i);
        if (it != tags.end()) {
          const move_tag    &tag      = it->second;
          const std::string &move_id  = tag.move_id;
          const std::string &raw_text = tag.raw_text;

          patched.set_attribute(kMvMoveAttr, move_id);

          if (!tag.partner_xpaths.empty()) {
            const std::string joined = join_xpath_union(tag.partner_xpaths);

            if (fn == "diff:delete") {
              patched.set_attribute(kMvToAttr, joined);
            } else { // diff:insert
              patched.set_attribute(kMvFromAttr, joined);
            }
          }

          writer.write(patched);

          move_entry &entry = moves[move_id];
          entry.move_id     = move_id;

          if (fn == "diff:delete") {
            entry.from_xpaths.push_back(xpath);
            entry.from_raw_texts.push_back(raw_text);
          } else {
            entry.to_xpaths.push_back(xpath);
            entry.to_raw_texts.push_back(raw_text);
          }

          ++i;
          continue;
        }
      }
    }

    writer.write(node);
    ++i;
  }

  return moves;
}

} // namespace

std::vector<move_entry> annotate(const std::vector<diff_region> &regions,
                                 const candidate_registry       &registry,
                                 const content_groups           &groups,
                                 const std::string &srcdiff_in_filename,
                                 const std::string &srcdiff_out_filename) {

  const tag_map tags = build_move_tags(groups, registry, srcdiff_in_filename);

  // second pass
  auto moves_map = write_with_move_annotations(srcdiff_in_filename,
                                               srcdiff_out_filename, tags);
  std::vector<move_entry> moves;
  moves.reserve(moves_map.size());

  for (auto &kv : moves_map)
    moves.push_back(std::move(kv.second));
  return moves;
}

} // namespace srcmove
