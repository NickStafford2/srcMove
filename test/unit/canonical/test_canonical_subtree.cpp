#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "move_candidate.hpp"
#include "parse/diff_region.hpp"
#include "region_filter.hpp"
#include "srcml_reader.hpp"

namespace fs = std::filesystem;
using namespace srcmove;

static std::string xml_dir() {
  return std::string(SRCMOVE_SOURCE_DIR) + "/test/canonical/generated";
}

static void require(bool cond, const std::string &msg) {
  if (!cond)
    throw std::runtime_error(msg);
}

static std::vector<move_candidate> load_candidates(const std::string &xml) {
  srcml_reader reader(xml);

  auto regions = collect_all_regions(reader);

  region_filter_options opt;
  opt.policy               = region_filter_policy::leaf_only;
  opt.drop_whitespace_only = true;
  opt.skip_pre_marked      = true;
  opt.min_chars            = 1;

  return filter_regions_for_registry(regions, opt);
}

static bool expect_equal(const std::string &filename) {
  auto pos = filename.find("__");
  if (pos == std::string::npos)
    return false;

  std::string left  = filename.substr(0, pos);
  std::string right = filename.substr(pos + 2);

  return left.find("same") == 0 && right.find("same") == 0;
}

static void run_case(const fs::path &file) {
  std::cout << "\nCASE: " << file.filename() << "\n";

  auto candidates = load_candidates(file);

  if (candidates.empty()) {
    std::cout << "  whitespace-only diff (ignored)\n";
    return;
  }

  const move_candidate *del = nullptr;
  const move_candidate *ins = nullptr;

  for (auto &c : candidates) {
    if (c.kind == move_candidate::Kind::del)
      del = &c;
    else
      ins = &c;
  }

  require(del, "missing delete candidate");
  require(ins, "missing insert candidate");

  bool equal = (del->canonical_text == ins->canonical_text);

  std::cout << "  canonical_equal = " << (equal ? "true" : "false") << "\n";

  if (expect_equal(file.filename()))
    require(equal, "expected canonical match");
  else
    require(!equal, "expected canonical difference");
}

int main() {
  try {
    auto dir = xml_dir();

    for (auto &entry : fs::directory_iterator(dir)) {
      if (entry.path().extension() == ".xml")
        run_case(entry.path());
    }

    std::cout << "\nPASS canonical tests\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "\nFAIL: " << e.what() << "\n";
    return 1;
  }
}
