// SPDX-License-Identifier: GPL-3.0-only
#ifndef INCLUDED_CONTENT_GROUP_BUILDER_HPP
#define INCLUDED_CONTENT_GROUP_BUILDER_HPP

#include "candidate_registry.hpp"
#include "move_groups.hpp"

namespace srcmove {

content_groups build_content_groups(const candidate_registry &registry,
                                    bool confirm_text_equality = true);

} // namespace srcmove

#endif
