// SPDX-License-Identifier: GPL-3.0-only
#include "location_context.hpp"

namespace srcmove {

std::pair<std::string, std::string>
split_revision_filename(std::string_view combined_filename) {
  const std::size_t separator = combined_filename.find('|');
  if (separator == std::string_view::npos) {
    const std::string shared(combined_filename);
    return {shared, shared};
  }
  return {
      std::string(combined_filename.substr(0, separator)),
      std::string(combined_filename.substr(separator + 1)),
  };
}

} // namespace srcmove
