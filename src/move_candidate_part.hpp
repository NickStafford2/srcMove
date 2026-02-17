#ifndef INCLUDED_MOVE_CANDIDATE_PART_HPP
#define INCLUDED_MOVE_CANDIDATE_PART_HPP

#include <string>
#include <utility>

namespace srcmove {

/*
locality of behavior
Use several factors to measure the confidence that something is a move.
  assign points to each one.
  can change values depending on user experience feedback.
size of the move
  small lines of code are more likely to be rewritten.
  giant functions moved across files are almost certainly moves
distance to move in the directory tree.
distance to move on page. rows/columns  --position
distance to move between blocks.
Similarity of the two code segments.

can be either original or modified.

either an insert or delete operation in a source diff
*/
struct move_candidate_part {

  // relative to the project root.
  std::string file_path;
  std::string file_name;

  // The whole move_candidate as a string as it appears in the diff
  std::string as_string;

  // string of all the parent blocks up unto the position
  std::string context;

  std::size_t number_of_characters;

  // distance to move on page. rows/columns  --position
  // row and column where the first letter of the first line appears
  std::pair<std::size_t, std::size_t> page_position;
};

} // namespace srcmove
#endif
