// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file uuid_generator.cpp
 */
#include "uuid_generator.hpp"

#include <iomanip>
#include <random>
#include <sstream>
#include <unordered_set>

namespace srcmove {

std::string get_uuid() {

  // The 64-bit RNG from the C++ <random>
  static std::mt19937_64                 rng(std::random_device{}());
  static std::unordered_set<std::string> used;

  for (;;) {
    // Generate 36 random bits for exactly 9 hexadecimal digits.
    const std::uint64_t value = rng() & 0xFFFFFFFFFull;

    std::ostringstream oss;
    oss << std::hex << std::nouppercase << std::setw(9) << std::setfill('0')
        << value;

    std::string id = oss.str();

    if (used.insert(id).second) {
      return id;
    }
  }
}

} // namespace srcmove
