// SPDX-License-Identifier: GPL-3.0-only
/**
 * @file profile.hpp
 *
 * Lightweight wall-clock profiling for coarse pipeline stages.
 */
#ifndef INCLUDED_MOVE_PROFILE_HPP
#define INCLUDED_MOVE_PROFILE_HPP

#include <chrono>
#include <iomanip>
#include <ostream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace srcmove {

class profile_report {
public:
  void add_ms(std::string name, double elapsed_ms) {
    entries_.push_back(entry{std::move(name), elapsed_ms});
  }

  bool empty() const noexcept { return entries_.empty(); }

  void write_text(std::ostream &out) const {
    std::ostringstream buffer;
    buffer << std::fixed << std::setprecision(3);
    for (const entry &e : entries_) {
      buffer << "profile." << e.name << "_ms=" << e.elapsed_ms << "\n";
    }
    out << buffer.str();
  }

private:
  struct entry {
    std::string name;
    double      elapsed_ms = 0.0;
  };

  std::vector<entry> entries_;
};

class scoped_profile_timer {
public:
  scoped_profile_timer(profile_report *profile, std::string name)
      : profile_(profile), name_(std::move(name)), start_(clock::now()) {}

  scoped_profile_timer(const scoped_profile_timer &)            = delete;
  scoped_profile_timer &operator=(const scoped_profile_timer &) = delete;

  ~scoped_profile_timer() {
    if (profile_ == nullptr) {
      return;
    }

    const auto end        = clock::now();
    const auto elapsed_us =
        std::chrono::duration_cast<std::chrono::duration<double, std::micro>>(
            end - start_);
    profile_->add_ms(name_, elapsed_us.count() / 1000.0);
  }

private:
  using clock = std::chrono::steady_clock;

  profile_report     *profile_ = nullptr;
  std::string         name_;
  clock::time_point   start_;
};

} // namespace srcmove

#endif
