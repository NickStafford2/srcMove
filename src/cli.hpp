// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file cli.hpp
 */
#ifndef INCLUDED_MOVE_CLI_HPP
#define INCLUDED_MOVE_CLI_HPP

#include <stdexcept>
#include <string>

namespace srcmove {

struct cli_options {
  std::string input_path;
  std::string output_path = "diff_new.xml";
  std::string results_path;
  bool verbose = false;
};

class cli_error : public std::runtime_error {
public:
  using std::runtime_error::runtime_error;
};

cli_options parse_cli(int argc, char **argv);
std::string usage(const std::string &progname);

} // namespace srcmove
#endif
