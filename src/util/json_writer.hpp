#ifndef INCLUDED_SRCMOVE_JSON_WRITER_HPP
#define INCLUDED_SRCMOVE_JSON_WRITER_HPP

#include <ostream>
#include <string>
#include <string_view>
#include <vector>

#include "summary.hpp"

namespace srcmove::json {

inline std::string escape(std::string_view s) {
  std::string out;
  out.reserve(s.size() + 8);

  for (char c : s) {
    switch (c) {
    case '"':
      out += "\\\"";
      break;
    case '\\':
      out += "\\\\";
      break;
    case '\n':
      out += "\\n";
      break;
    case '\r':
      out += "\\r";
      break;
    case '\t':
      out += "\\t";
      break;
    default:
      out.push_back(c);
      break;
    }
  }

  return out;
}

inline void write_string(std::ostream &out, std::string_view s) {
  out << "\"" << escape(s) << "\"";
}

inline void write_string_array(std::ostream                   &out,
                               const std::vector<std::string> &arr,
                               std::size_t                     indent) {
  const std::string pad(indent, ' ');
  const std::string item_pad(indent + 2, ' ');

  out << "[\n";

  for (std::size_t i = 0; i < arr.size(); ++i) {
    out << item_pad;
    write_string(out, arr[i]);
    if (i + 1 < arr.size()) {
      out << ",";
    }
    out << "\n";
  }

  out << pad << "]";
}

inline void write_move_entry(std::ostream     &out,
                             const move_entry &m,
                             std::size_t       indent = 4) {
  const std::string pad(indent, ' ');
  const std::string field_pad(indent + 2, ' ');

  out << pad << "{\n";
  out << field_pad << "\"move_id\": " << m.move_id << ",\n";

  out << field_pad << "\"from_xpaths\": ";
  write_string_array(out, m.from_xpaths, indent + 2);
  out << ",\n";

  out << field_pad << "\"to_xpaths\": ";
  write_string_array(out, m.to_xpaths, indent + 2);
  out << ",\n";

  out << field_pad << "\"from_raw_texts\": ";
  write_string_array(out, m.from_raw_texts, indent + 2);
  out << ",\n";

  out << field_pad << "\"to_raw_texts\": ";
  write_string_array(out, m.to_raw_texts, indent + 2);
  out << "\n";

  out << pad << "}";
}

inline void write_summary(std::ostream &out, const summary &summ) {
  out << "{\n";
  out << "  \"move_count\": " << summ.move_count << ",\n";
  out << "  \"moves\": [\n";

  for (std::size_t i = 0; i < summ.moves.size(); ++i) {
    write_move_entry(out, summ.moves[i], 4);
    if (i + 1 < summ.moves.size())
      out << ",";
    out << "\n";
  }

  out << "  ],\n";
  out << "  \"annotated_regions\": " << summ.annotated_regions << ",\n";
  out << "  \"regions_total\": " << summ.regions_total << ",\n";
  out << "  \"candidates_total\": " << summ.candidates_total << ",\n";
  out << "  \"groups_total\": " << summ.groups_total << "\n";
  out << "}\n";
}

} // namespace srcmove::json

#endif
