#include "cli.hpp"

#include <sstream>
#include <string>

namespace srcmove {

std::string usage(const std::string &progname) {
  std::ostringstream out;
  out << "usage: " << progname
      << " <srcdiff.xml> [out.xml] [--results results.json] [-v]\n";
  return out.str();
}

cli_options parse_cli(int argc, char **argv) {
  if (argc < 2) {
    throw cli_error(usage(argv[0]));
  }

  cli_options opts;
  opts.input_path = argv[1];

  int i = 2;

  if (i < argc && std::string(argv[i]).rfind("-", 0) != 0) {
    opts.output_path = argv[i];
    ++i;
  }

  for (; i < argc; ++i) {
    const std::string arg = argv[i];

    if (arg == "--results") {
      if (i + 1 >= argc) {
        throw cli_error("Error: --results requires a file path\n" +
                        usage(argv[0]));
      }
      opts.results_path = argv[++i];
    } else if (arg == "-v" || arg == "--verbose") {
      opts.verbose = true;
    } else if (arg == "-h" || arg == "--help") {
      throw cli_error(usage(argv[0]));
    } else {
      throw cli_error("Error: unknown argument: " + arg + "\n" +
                      usage(argv[0]));
    }
  }

  return opts;
}

} // namespace srcmove
