#include "cli.hpp"
#include "srcmove/version.hpp"

#include <sstream>
#include <string>

namespace srcmove {

namespace {

std::string build_help(const std::string &progname) {
  std::ostringstream out;
  out << "srcMove - detect moved code regions in a srcDiff document\n\n";
  out << "Usage:\n";
  out << "  " << progname
      << " <srcdiff.xml> [out.xml] [--results results.json]"
         " [--results-only] [--min-granularity statement|fragment]"
         " [--diagnostics] [--profile] [-v]\n";
  out << "  " << progname << " --help\n";
  out << "  " << progname << " --version\n\n";

  out << "Arguments:\n";
  out << "  <srcdiff.xml>          Input srcDiff XML file\n";
  out << "  [out.xml]              Output annotated XML file "
      << "(default: " << DEFAULT_OUTPUT_PATH << ")\n\n";

  out << "Options:\n";
  out << "  --results <file>       Write summary JSON to <file>\n";
  out << "  --results-only        Write JSON without annotated XML; requires"
         " --results and no out.xml\n";
  out << "  --profile              Write coarse timing data to stderr\n";
  out << "  --diagnostics          Include candidate and Type-3 decision evidence"
         " in results JSON\n";
  out << "  --min-granularity <statement|fragment>\n";
  out << "                         Minimum move unit (default: statement)\n";
  out << "  -v, --verbose          Print move-match debug output to stdout\n";
  out << "  -h, --help             Show this help message and exit\n";
  out << "  --version              Show version information and exit\n";

  return out.str();
}

std::string build_version() { return "srcMove v" + std::string(VERSION); }

} // namespace

std::string usage(const std::string &progname) { return build_help(progname); }

cli_options parse_cli(int argc, char **argv) {
  cli_options opts;

  bool have_input  = false;
  bool have_output = false;

  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];

    if (arg == "-h" || arg == "--help") {
      throw cli_exit(build_help(argv[0]));
    }

    if (arg == "--version") {
      throw cli_exit(build_version());
    }

    if (arg == "-v" || arg == "--verbose") {
      opts.verbose = true;
      continue;
    }

    if (arg == "--profile") {
      opts.profile = true;
      continue;
    }

    if (arg == "--results-only") {
      opts.results_only = true;
      continue;
    }

    if (arg == "--diagnostics") {
      opts.diagnostics = true;
      continue;
    }

    if (arg == "--min-granularity") {
      if (i + 1 >= argc) {
        throw cli_error("Error: --min-granularity requires statement or fragment\n\n" +
                        build_help(argv[0]));
      }
      const std::string value = argv[++i];
      if (value == "statement") {
        opts.min_granularity = minimum_move_granularity::statement;
      } else if (value == "fragment") {
        opts.min_granularity = minimum_move_granularity::fragment;
      } else {
        throw cli_error("Error: invalid --min-granularity value: " + value +
                        "\n\n" + build_help(argv[0]));
      }
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
      have_input      = true;
      continue;
    }

    if (!have_output) {
      opts.output_path = arg;
      have_output      = true;
      continue;
    }

    throw cli_error("Error: too many positional arguments\n\n" +
                    build_help(argv[0]));
  }

  if (!have_input) {
    throw cli_error("Error: missing input srcdiff.xml\n\n" +
                    build_help(argv[0]));
  }

  if (opts.results_only && opts.results_path.empty()) {
    throw cli_error("Error: --results-only requires --results <file>\n\n" +
                    build_help(argv[0]));
  }

  if (opts.results_only && have_output) {
    throw cli_error("Error: --results-only does not accept an output XML path\n\n" +
                    build_help(argv[0]));
  }

  if (opts.diagnostics && opts.results_path.empty()) {
    throw cli_error("Error: --diagnostics requires --results <file>\n\n" +
                    build_help(argv[0]));
  }

  return opts;
}

} // namespace srcmove
