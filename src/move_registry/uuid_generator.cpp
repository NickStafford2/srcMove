// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file uuid_generator.cpp
 */
#include "move_registry/uuid_generator.hpp"

#include <cstdint>
#include <iomanip>
#include <sstream>

namespace srcmove {
namespace {

// Cheap deterministic 64-bit mixer.
// This is not cryptographic. It only scrambles nearby counter values
// so the resulting ids do not visibly look sequential.
std::uint64_t mix64(std::uint64_t x) {
  x ^= x >> 30;
  x *= 0xbf58476d1ce4e5b9ULL;
  x ^= x >> 27;
  x *= 0x94d049bb133111ebULL;
  x ^= x >> 31;
  return x;
}

} // namespace

std::string get_uuid() {
  static std::uint64_t    counter = 0;
  constexpr std::uint64_t seed    = 0x9e3779b97f4a7c15ULL;

  const std::uint64_t value       = mix64(seed + counter++);
  const std::uint64_t short_value = value & 0xFFFFFFFFFULL; // 9 hex digits

  std::ostringstream oss;
  oss << std::hex << std::nouppercase << std::setw(9) << std::setfill('0')
      << short_value;

  return oss.str();
}

} // namespace srcmove
