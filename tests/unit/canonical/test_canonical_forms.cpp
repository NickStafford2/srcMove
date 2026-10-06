#include "parse/canonical_subtree.hpp"

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace srcmove;

namespace {
void require(bool condition, const char *message) {
  if (!condition) throw std::runtime_error(message);
}

srcml_node tag(const std::string &name, bool start = true, bool diff = false) {
  srcml_node node;
  node.type = start ? srcml_node::START : srcml_node::END;
  node.name = name;
  node.ns = diff ? std::make_shared<srcml_node::srcml_namespace>(
                      "http://www.srcML.org/srcDiff", std::string("diff"))
                 : srcml_node::SRC_NAMESPACE;
  return node;
}

void element(std::vector<srcml_node> &nodes, const std::string &name,
             const std::string &text) {
  auto start = tag(name);
  if (name == "literal") start.set_attribute("type", "number");
  nodes.push_back(start);
  nodes.emplace_back(text);
  nodes.push_back(tag(name, false));
}

std::vector<srcml_node> expression(const std::string &left = "value",
                                   const std::string &right = "value",
                                   const std::string &literal = "17",
                                   const std::string &op = "+") {
  std::vector<srcml_node> nodes{tag("expr_stmt"), tag("expr")};
  element(nodes, "name", left);
  element(nodes, "operator", "=");
  element(nodes, "name", right);
  element(nodes, "operator", op);
  element(nodes, "literal", literal);
  nodes.push_back(tag("expr", false));
  nodes.emplace_back(";");
  nodes.push_back(tag("expr_stmt", false));
  return nodes;
}

canonical_forms forms(const std::vector<srcml_node> &nodes,
                      bool projections = true) {
  canonical_forms_builder builder(projections, projections);
  for (const auto &node : nodes) builder.consume(node);
  return builder.finish();
}

std::vector<srcml_node> member_expression(const std::string &second_owner) {
  std::vector<srcml_node> nodes{tag("expr")};
  for (const std::string owner : {std::string("first"), second_owner}) {
    nodes.push_back(tag("name"));
    element(nodes, "name", owner);
    element(nodes, "operator", ".");
    element(nodes, "name", "member");
    nodes.push_back(tag("name", false));
  }
  nodes.push_back(tag("expr", false));
  return nodes;
}
} // namespace

int main() {
  try {
    const auto original_nodes = expression();
    const auto original = forms(original_nodes);
    require(!original.exact.empty() && !original.type2_canonical.empty() &&
                !original.names_only_canonical.empty(),
            "finite fixture must produce all requested projections");
    require(!original.normalized_tokens.empty() && !original.normalized_lines.empty(),
            "similarity projections must be populated");
    require(original.identifier_names == std::vector<std::string>{"value"},
            "repeated identifiers have one identity in occurrence order");

    const auto renamed = forms(expression("other", "other"));
    require(original.exact != renamed.exact, "exact identity preserves names");
    require(original.type2_canonical == renamed.type2_canonical &&
                original.names_only_canonical == renamed.names_only_canonical &&
                original.normalized_tokens == renamed.normalized_tokens,
            "bijective renaming preserves consistent projections");
    const auto inconsistent = forms(expression("other", "third"));
    require(original.type2_canonical != inconsistent.type2_canonical &&
                original.names_only_canonical != inconsistent.names_only_canonical,
            "inconsistent renaming cannot corroborate identity");
    require(original.type2b_canonical == inconsistent.type2b_canonical,
            "blind diagnostic projection does not claim consistent renaming");

    const auto changed_literal = forms(expression("value", "value", "23"));
    require(original.exact != changed_literal.exact &&
                original.names_only_canonical != changed_literal.names_only_canonical,
            "identity projection preserves literal changes");
    require(original.type2_canonical == changed_literal.type2_canonical,
            "Type-2 projection normalizes same-category literals");
    require(original.type2_canonical != forms(expression("value", "value", "17", "-")).type2_canonical,
            "operator changes are not identifier renaming");

    auto syntax_changed = original_nodes;
    syntax_changed.push_back(tag("empty_stmt"));
    syntax_changed.emplace_back(";");
    syntax_changed.push_back(tag("empty_stmt", false));
    require(original.type2_canonical != forms(syntax_changed).type2_canonical,
            "added empty statement remains syntax");

    auto decorated = original_nodes;
    decorated.insert(decorated.begin(), tag("delete", true, true));
    decorated.insert(decorated.begin() + 1, tag("common", true, true));
    decorated.push_back(tag("common", false, true));
    decorated.push_back(tag("delete", false, true));
    decorated.emplace_back(" \n\t");
    element(decorated, "comment", "/* unrelated_identifier + 99 */");
    const auto transparent = forms(decorated);
    require(original.exact == transparent.exact &&
                original.type2_canonical == transparent.type2_canonical &&
                original.names_only_canonical == transparent.names_only_canonical &&
                original.identifier_names == transparent.identifier_names &&
                original.normalized_tokens == transparent.normalized_tokens,
            "revision wrappers, comments and whitespace cannot invent evidence");

    std::vector<srcml_node> fragmented{tag("name"), srcml_node("frag"),
                                     tag("common", true, true), srcml_node("ment"),
                                     tag("common", false, true), tag("name", false)};
    require(forms(fragmented).fragmented_identifier,
            "multiple text events in one name must mark fragmented identity");
    require(!original.fragmented_identifier,
            "repeated complete names are not fragmented identifiers");

    const auto qualified = forms(member_expression("first"));
    require(qualified.member_accesses.size() == 2 &&
                qualified.member_accesses[0] == std::make_pair(std::string("first.member"), std::string("first.")),
            "member access keeps its actual qualifier and occurrence multiplicity");
    const auto conflicting = forms(member_expression("second"));
    bool ambiguous = false;
    for (std::size_t i = 0; i < conflicting.identifier_names.size(); ++i) {
      if (conflicting.identifier_names[i] == "member")
        ambiguous = conflicting.identifier_qualifiers.at(i) == "$ambiguous";
    }
    require(ambiguous, "one name used under different owners cannot claim one qualifier");

    const auto ordinary = forms(original_nodes, false);
    require(ordinary.exact == original.exact && ordinary.type2_canonical == original.type2_canonical &&
                ordinary.names_only_canonical.empty() && ordinary.type2b_canonical.empty(),
            "optional projections must not alter ordinary canonicalization");
    std::cout << "PASS canonical forms: identity, literals, syntax, wrappers, fragmentation and qualifiers\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL canonical forms: " << error.what() << '\n';
    return 1;
  }
}
