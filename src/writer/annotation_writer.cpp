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
#include "diff_region.hpp"
#include "move_registry/candidate_registry.hpp"
#include "move_registry/move_groups.hpp"
#include "srcml_node.hpp"
#include "srcml_reader.hpp"
#include "srcml_writer.hpp"
#include "xpath_builder.hpp"

namespace srcmove {

namespace {

void write_with_move_annotations(const std::string &in_filename,
                                 const std::string &out_filename,
                                 const tag_map &tags) {
  srcml_reader reader(in_filename);
  srcml_writer writer(out_filename);
  xpath_builder xb;

  std::size_t i = 0;
  for (const srcml_node &node : reader) {
    xb.on_node(node);

    // Patch only START tags of diff:insert / diff:delete when we have a tag.
    if (node.is_start()) {
      const std::string fn = node.full_name();
      if (fn == "diff:insert" || fn == "diff:delete") {
        srcml_node patched = node; // copy so we don't mutate reader-owned node

        // If srcDiff already marked it, never overwrite move,
        // but still attach xpath.
        if (node.get_attribute_value("move")) {
          patched.set_attribute("xpath", xb.current_xpath());
          writer.write(patched);
          ++i;
          continue;
        }

        auto it = tags.find(i);
        if (it != tags.end()) {
          patched.set_attribute("move", std::to_string(it->second.move_id));
          patched.set_attribute("xpath", xb.current_xpath());
          writer.write(patched);
          ++i;
          continue;
        }
      }
    }

    writer.write(node);
    ++i;
  }
}

} // namespace

int annotate(const std::vector<diff_region> &regions,
             const candidate_registry &registry, const content_groups &groups,
             const std::string &srcdiff_in_filename,
             const std::string &srcdiff_out_filename) {
  const std::uint32_t start_move_id = max_existing_move_id(regions) + 1;
  const auto tags = build_move_tags(groups, registry, start_move_id);

  // second pass
  write_with_move_annotations(srcdiff_in_filename, srcdiff_out_filename, tags);
  return tags.size();
}

} // namespace srcmove
