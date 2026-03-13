#include <fstream>
#include <iostream>

#include "cli.hpp"
#include "pipeline.hpp"
#include "summary.hpp"
#include "util/json_writer.hpp"

int main(int argc, char **argv) {
  try {
    const srcmove::cli_options opts = srcmove::parse_cli(argc, argv);

    const srcmove::summary summ =
        srcmove::run_pipeline(opts.input_path, opts.output_path);

    if (!opts.results_path.empty()) {
      std::ofstream out(opts.results_path);
      if (!out) {
        std::cerr << "Error: could not open results file: " << opts.results_path
                  << "\n";
        return 2;
      }
      srcmove::json::write_summary(out, summ);
    }

    return 0;
  } catch (const srcmove::cli_error &e) {
    std::cerr << e.what() << "\n";
    return 1;
  } catch (const std::exception &e) {
    std::cerr << "Error: " << e.what() << "\n";
    return 2;
  }
}
