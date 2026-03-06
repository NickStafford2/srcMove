#include <fstream>
#include <iostream>
#include <string>

#include "pipeline.hpp"
#include "summary.hpp"
#include "util/json_writer.hpp"

int main(int argc, char **argv) {
  if (argc < 2) {
    std::cerr << "usage: " << argv[0]
              << " <srcdiff.xml> [out.xml] [--results results.json]\n";
    return 1;
  }

  const std::string in_filename = argv[1];
  std::string out_filename = "diff_new.xml";
  std::string results_path;

  int i = 2;

  // optional positional out.xml, only if next arg is not a flag
  if (i < argc && std::string(argv[i]).rfind("--", 0) != 0) {
    out_filename = argv[i];
    ++i;
  }

  // parse remaining flags
  for (; i < argc; ++i) {
    const std::string arg = argv[i];

    if (arg == "--results") {
      if (i + 1 >= argc) {
        std::cerr << "Error: --results requires a file path\n";
        return 1;
      }
      results_path = argv[++i];
    } else {
      std::cerr << "Error: unknown argument: " << arg << "\n";
      std::cerr << "usage: " << argv[0]
                << " <srcdiff.xml> [out.xml] [--results results.json]\n";
      return 1;
    }
  }

  try {
    const srcmove::summary summ =
        srcmove::run_pipeline(in_filename, out_filename);

    if (!results_path.empty()) {
      std::ofstream out(results_path);
      if (!out) {
        std::cerr << "Error: could not open results file: " << results_path
                  << "\n";
        return 2;
      }
      out << "{\n";
      out << "  \"move_count\": " << summ.move_count << ",\n";
      out << "  \"moves\": [\n";

      for (size_t i = 0; i < summ.moves.size(); ++i) {
        srcmove::json::write_move_entry(out, summ.moves[i], 4);
        if (i + 1 < summ.moves.size()) {
          out << ",";
        }
        out << "\n";
      }

      out << "  ],\n";
      out << "  \"annotated_regions\": " << summ.annotated_regions << ",\n";
      out << "  \"regions_total\": " << summ.regions_total << ",\n";
      out << "  \"candidates_total\": " << summ.candidates_total << ",\n";
      out << "  \"groups_total\": " << summ.groups_total << "\n";
      out << "}\n";
    }
  } catch (const std::exception &e) {
    std::cerr << "Error: " << e.what() << "\n";
    return 2;
  }

  return 0;
}
