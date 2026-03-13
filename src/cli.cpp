#include "cli.hpp"

#include <sstream>
#include <string>

namespace srcmove {

namespace {

std::string build_help(const std::string &progname) {
  std::ostringstream out;
  out << "srcMove - detect moved code regions in a srcDiff document\n\n";
  out << "Usage:\n";
  out << "  " << progname
      << " <srcdiff.xml> [out.xml] [--results results.json] [-v]\n";
  out << "  " << progname << " --help\n";
  out << "  " << progname << " --version\n\n";

  out << "Arguments:\n";
  out << "  <srcdiff.xml>          Input srcDiff XML file\n";
  out << "  [out.xml]              Output annotated XML file "
         "(default: diff_new.xml)\n\n";

  out << "Options:\n";
  out << "  --results <file>       Write summary JSON to <file>\n";
  out << "  -v, --verbose          Enable verbose output\n";
  out << "  -h, --help             Show this help message and exit\n";
  out << "  --version              Show version information and exit\n";

  return out.str();
}

std::string build_version() { return "srcMove v0.1.1"; }

} // namespace

std::string usage(const std::string &progname) { return build_help(progname); }

cli_options parse_cli(int argc, char **argv) {
  cli_options opts;
  opts.output_path = "diff_new.xml";

  bool have_input = false;
  bool have_output = false;

  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];

    if (arg == "-h" || arg == "--help") {
      throw cli_error(build_help(argv[0]));
    }

    if (arg == "--version") {
      throw cli_error(build_version());
    }

    if (arg == "-v" || arg == "--verbose") {
      opts.verbose = true;
      continue;
    }

    if (arg == "--results") {
      if (i + 1 >= argc) {
        throw cli_error("Error: --results requires a file path\n\n" +
                        build_help(argv[0]));
      }
      opts.results_path = argv[++i];
      continue;
    }

    if (!arg.empty() && arg[0] == '-') {
      throw cli_error("Error: unknown argument: " + arg + "\n\n" +
                      build_help(argv[0]));
    }

    if (!have_input) {
      opts.input_path = arg;
      have_input = true;
      continue;
    }

    if (!have_output) {
      opts.output_path = arg;
      have_output = true;
      continue;
    }

    throw cli_error("Error: too many positional arguments\n\n" +
                    build_help(argv[0]));
  }

  if (!have_input) {
    throw cli_error("Error: missing input srcdiff.xml\n\n" +
                    build_help(argv[0]));
  }

  return opts;
}

} // namespace srcmove
