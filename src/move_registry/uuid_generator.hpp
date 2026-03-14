// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file uuid_generator.hpp
 */
#ifndef MOVE_UUID_GENERATOR_HPP
#define MOVE_UUID_GENERATOR_HPP

#include <string>

namespace srcmove {

/**
 * Generates short unique IDs for move annotations.
 *
 * Why this exists:
 *
 * Move identifiers in srcMove annotations should NOT imply any ordering
 * in which the developer performed moves. Sequential IDs like 1,2,3...
 * This may suggest to users an order that does not actually exist in
 * the source diff.
 *
 * Instead we generate short random hexadecimal IDs.
 *
 * The generator produces 9-digit hexadecimal IDs
 * A small set is used to prevent collisions within the current run.
 *
 * Random numbers are produced using std::mt19937_64, the 64-bit
 * Mersenne Twister provided by the C++ standard library.
 */

// Returns a unique 9-digit hexadecimal ID (example: "03fa92c1b")
std::string get_uuid();

} // namespace srcmove
#endif
