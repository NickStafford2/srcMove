#ifndef INCLUDED_MOVE_SELECTION_DIAGNOSTICS_HPP
#define INCLUDED_MOVE_SELECTION_DIAGNOSTICS_HPP

#include <cstddef>
#include <string>
#include <vector>

namespace srcmove {

struct candidate_diagnostic {
  std::size_t candidate_id = 0;
  std::string side;
  std::string filename;
  std::string xpath;
  std::string construct;
  std::string role;
  std::string raw_text;
  bool        type3_eligible = false;
  std::size_t line_units = 0;
  std::size_t token_units = 0;
};

struct type3_pair_diagnostic {
  std::size_t del_candidate_id = 0;
  std::size_t ins_candidate_id = 0;
  std::string outcome;
  std::size_t common_lines = 0;
  std::size_t maximum_lines = 0;
  std::size_t common_tokens = 0;
  std::size_t maximum_tokens = 0;
};

struct selection_diagnostics {
  std::vector<candidate_diagnostic> candidates;
  std::vector<type3_pair_diagnostic> type3_pairs;
};

} // namespace srcmove

#endif
