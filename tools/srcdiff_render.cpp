// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file srcdiff_render.cpp
 *
 * Render srcDiff XML into a raw-ish debugging view (no XML noise).
 *
 * Strategy:
 * - Stream nodes with srcml_reader.
 * - Track current unit filename.
 * - When we enter <diff:insert> or <diff:delete>, capture
 * reader.get_current_inner_text() (raw inner text as srcReader provides it) and
 * remember the start node index + attrs.
 * - When we see the matching end tag, print a block including filename,
 * start/end indices, and optional move/xpath attributes if present.
 *
 * Notes:
 * - This intentionally preserves whitespace in the captured inner text.
 * - Nested diff regions are handled via a stack.
 */

#include <iostream>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "srcml_node.hpp"
#include "srcml_reader.hpp"

namespace srcmove {

enum class diff_kind { insert, del };

static std::optional<diff_kind> diff_kind_from_full_name(std::string_view fn) {
  if (fn == "diff:insert")
    return diff_kind::insert;
  if (fn == "diff:delete")
    return diff_kind::del;
  return std::nullopt;
}

static const char *kind_label(diff_kind k) {
  return (k == diff_kind::insert) ? "INS" : "DEL";
}

struct open_region {
  diff_kind kind;
  std::string filename;

  std::size_t start_idx = 0;
  std::size_t end_idx = 0;

  // capture raw-ish inner text at START (as provided by srcReader)
  std::string inner_text;

  // attrs on the START tag (if present)
  std::string move_attr;
  std::string xpath_attr;
};

static void print_region(std::ostream &os, const open_region &r) {
  os << "==== " << kind_label(r.kind) << " ====\n";
  os << "file: " << r.filename << "\n";
  os << "node_span: [" << r.start_idx << "," << r.end_idx << "]\n";
  if (!r.move_attr.empty())
    os << "move: " << r.move_attr << "\n";
  if (!r.xpath_attr.empty())
    os << "xpath: " << r.xpath_attr << "\n";

  os << "---- BEGIN TEXT ----\n";
  // Preserve whitespace; avoid iostream formatting.
  os.write(r.inner_text.data(),
           static_cast<std::streamsize>(r.inner_text.size()));
  if (!r.inner_text.empty() && r.inner_text.back() != '\n')
    os << "\n";
  os << "---- END TEXT ----\n\n";
}

} // namespace srcmove

int main(int argc, char **argv) {
  if (argc != 2) {
    std::cerr << "usage: " << argv[0] << " <srcdiff.xml>\n";
    return 1;
  }

  const std::string in_filename = argv[1];

  try {
    srcml_reader reader(in_filename);

    std::string current_file;
    std::vector<srcmove::open_region> stack;
    stack.reserve(64);

    std::size_t node_index = 0;
    for (const srcml_node &node : reader) {

      // Track unit filename.
      if (node.is_start() && node.name == "unit") {
        if (const std::string *f = node.get_attribute_value("filename"))
          current_file = *f;
        else
          current_file.clear();
      }

      const std::string fn = node.full_name();

      if (node.is_start()) {
        if (auto k = srcmove::diff_kind_from_full_name(fn)) {
          srcmove::open_region r;
          r.kind = *k;
          r.filename = current_file;
          r.start_idx = node_index;
          r.inner_text = reader.get_current_inner_text();

          if (const std::string *mv = node.get_attribute_value("move"))
            r.move_attr = *mv;
          if (const std::string *xp = node.get_attribute_value("xpath"))
            r.xpath_attr = *xp;

          stack.push_back(std::move(r));
        }
      }

      if (node.is_end()) {
        if (auto k = srcmove::diff_kind_from_full_name(fn)) {
          if (stack.empty()) {
            std::cerr << "error: diff end without start at node_index="
                      << node_index << "\n";
            return 2;
          }

          // Validate nesting kind.
          auto r = std::move(stack.back());
          stack.pop_back();

          if (r.kind != *k) {
            std::cerr << "error: diff nesting mismatch at node_index="
                      << node_index << "\n";
            return 3;
          }

          r.end_idx = node_index;
          srcmove::print_region(std::cout, r);
        }
      }

      ++node_index;
    }

    if (!stack.empty()) {
      std::cerr << "error: diff region never closed (missing end tag?)\n";
      return 4;
    }

  } catch (const std::exception &e) {
    std::cerr << "Error: " << e.what() << "\n";
    return 10;
  }

  return 0;
}
