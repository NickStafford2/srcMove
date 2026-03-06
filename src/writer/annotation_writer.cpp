// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file annotation_writer.cpp
 *
 * Writes the annotated srcDiff document by copying the input stream and
 * patching move-related attributes onto diff start tags.
 */
#include <cctype>
#include <string>
#include <vector>

// uncomment to disable assert()
// #define NDEBUG
#include <cassert>

#include "annotation_plan.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/move_groups.hpp"
#include "parse/diff_region.hpp"
#include "srcml_node.hpp"
#include "srcml_reader.hpp"
#include "srcml_writer.hpp"
#include "summary.hpp"
#include "xpath_builder.hpp"

namespace srcmove {

namespace {

std::unordered_map<std::uint32_t, move_entry>
write_with_move_annotations(const std::string &in_filename,
                            const std::string &out_filename,
                            const tag_map &tags) {
  srcml_reader reader(in_filename);
  srcml_writer writer(out_filename);
  xpath_builder xb;
  std::unordered_map<std::uint32_t, move_entry> moves;

  std::size_t i = 0;
  for (const srcml_node &node : reader) {
    xb.on_node(node);

    if (node.is_start()) {
      const std::string fn = node.full_name();

      if (fn == "diff:insert" || fn == "diff:delete") {
        srcml_node patched = node;
        const std::string xpath = xb.current_xpath();

        if (const std::string *existing_move =
                node.get_attribute_value("move")) {
          patched.set_attribute("xpath", xpath);
          writer.write(patched);

          try {
            const std::uint32_t move_id =
                static_cast<std::uint32_t>(std::stoul(*existing_move));

            auto &entry = moves[move_id];
            entry.move_id = move_id;

            if (fn == "diff:delete") {
              entry.from_xpaths.push_back(xpath);
            } else {
              entry.to_xpaths.push_back(xpath);
            }
          } catch (...) {
          }

          ++i;
          continue;
        }

        auto it = tags.find(i);
        if (it != tags.end()) {
          const std::uint32_t move_id = it->second.move_id;

          patched.set_attribute("move", std::to_string(move_id));
          patched.set_attribute("xpath", xpath);
          writer.write(patched);

          auto &entry = moves[move_id];
          entry.move_id = move_id;

          if (fn == "diff:delete") {
            entry.from_xpaths.push_back(xpath);
          } else {
            entry.to_xpaths.push_back(xpath);
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
                                 const candidate_registry &registry,
                                 const content_groups &groups,
                                 const std::string &srcdiff_in_filename,
                                 const std::string &srcdiff_out_filename) {
  const std::uint32_t start_move_id = max_existing_move_id(regions) + 1;
  const auto tags = build_move_tags(groups, registry, start_move_id);

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
