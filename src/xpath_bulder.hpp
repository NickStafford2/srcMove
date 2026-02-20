#include <cassert>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

namespace srcmove {

class xpath_builder {
public:
  // Call this for every node in the stream, in order.
  void on_node(const srcml_node &node) {
    if (node.is_start())
      on_start(node);
    else if (node.is_end())
      on_end(node);
    // TEXT nodes don't affect element path
  }

  // Current element path (to the current open element stack).
  std::string current_xpath() const {
    if (stack_.empty())
      return "/";

    std::ostringstream os;
    for (const auto &f : stack_) {
      os << "/" << f.name << "[" << f.index << "]";
    }
    return os.str();
  }

  // Convenience: what would the path be for a START node you just saw?
  // (After calling on_node(node), current_xpath() already reflects it.)
  // Provided mainly for readability.

private:
  struct Frame {
    std::string name;  // full_name()
    std::size_t index; // 1-based among siblings with same name under parent
    std::unordered_map<std::string, std::size_t> child_counts;
  };

  std::vector<Frame> stack_;

  void on_start(const srcml_node &node) {
    const std::string name = node.full_name();

    std::size_t idx = 1;
    if (!stack_.empty()) {
      auto &counts = stack_.back().child_counts;
      idx = ++counts[name]; // increment and use
    }

    stack_.push_back(Frame{name, idx, {}});
  }

  void on_end(const srcml_node &node) {
    // In a well-formed stream, the top should match.
    // srcReader sometimes synthesizes END for empty elements; it should still
    // match by name.
    assert(!stack_.empty() && "END with empty stack");
    // You can relax this if needed, but it's a good sanity check:
    // assert(stack_.back().name == node.full_name() && "Mismatched END tag");
    stack_.pop_back();
  }
};

} // namespace srcmove
