#!/usr/bin/env python3
"""Check the proposed locator convention using hand-authored native XML.

This tests interpretation of existing strings, not srcReader generation or
srcMove correctness. No detector executes and no experimental evidence is made.
"""

import json
from pathlib import Path

try:
    from lxml import etree
except ImportError as error:
    raise SystemExit("Install requirements-validation.txt into the validation target.") from error


SRC = "http://www.srcML.org/srcML/src"
DIFF = "http://www.srcML.org/srcDiff"
MV = "http://www.srcML.org/srcMove"
NS = {"src": SRC, "diff": DIFF, "mv": MV}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def parse(text):
    return etree.ElementTree(etree.fromstring(
        text, etree.XMLParser(resolve_entities=False, no_network=True)))


def archive_mode(tree):
    root = tree.getroot()
    attributes = {etree.QName(name).localname for name in root.attrib}
    return (etree.QName(root).localname == "unit"
            and "url" in attributes and "filename" not in attributes)


def resolve(tree, locator, namespaces):
    require(namespaces.get("src") == SRC and namespaces.get("diff") == DIFF,
            "Incorrect canonical namespace bindings")
    expression = ("/src:unit[1]" if archive_mode(tree) else "") + locator
    try:
        matches = tree.xpath(expression, namespaces=namespaces)
    except etree.XPathError as error:
        raise ValueError(f"Invalid or unbound locator: {locator}") from error
    require(isinstance(matches, list) and len(matches) == 1
            and isinstance(matches[0], etree._Element),
            f"Locator must resolve exactly once: {locator}")
    return matches[0]


def signature(node):
    """Ignore only move attributes, retaining source text and XML structure."""
    attributes = {name: value for name, value in node.attrib.items()
                  if etree.QName(name).namespace != MV}
    return (node.tag, attributes, node.text, node.tail,
            [signature(child) for child in node])


def check_companions(directory, case, namespaces):
    original = parse((directory / case["input"]).read_bytes())
    annotated = parse((directory / case["annotated"]).read_bytes())
    require(archive_mode(original) == archive_mode(annotated) == case["archive"],
            "Fixture archive classification disagrees")
    require(signature(original.getroot()) == signature(annotated.getroot()),
            "Annotated companion changed source structure or text")
    for endpoint in case["endpoints"]:
        before = resolve(original, endpoint["xpath"], namespaces)
        after = resolve(annotated, endpoint["xpath"], namespaces)
        require("".join(before.itertext()) == "".join(after.itertext())
                == endpoint["raw_text"], "Resolved endpoint text disagrees")
        require(after.get(f"{{{MV}}}id") == endpoint["group_id"],
                "Atomic annotation ID disagrees")
        attribute = f"{{{MV}}}{endpoint['partner_attribute']}"
        require(after.get(attribute) == endpoint["partner_xpath"],
                "Partner locator attribute disagrees")
        partner = resolve(annotated, endpoint["partner_xpath"], namespaces)
        require(partner.get(f"{{{MV}}}id") == endpoint["group_id"],
                "Partner does not share atomic ID")


def xpath_literal(value):
    if "'" not in value:
        return "'" + value + "'"
    if '"' not in value:
        return '"' + value + '"'
    return "concat(" + ',"\'",'.join("'" + part + "'" for part in value.split("'")) + ")"


def edge_checks():
    checks = 0

    def rejects(callback):
        try:
            callback()
        except ValueError:
            return
        raise ValueError("Malformed locator case was accepted")

    # Alternate input prefixes still use canonical emitted src/diff bindings.
    body = f'<s:unit xmlns:s="{SRC}" xmlns:d="{DIFF}" filename="a.cpp"><d:delete><s:expr_stmt>x();</s:expr_stmt></d:delete></s:unit>'
    single = parse(body.encode())
    locator = "/src:unit[1]/diff:delete[1]/src:expr_stmt[1]"
    require("".join(resolve(single, locator, NS).itertext()) == "x();", "Prefix alias failure")
    checks += 1
    single.getroot().set("url", "synthetic://both-attributes")
    require(not archive_mode(single), "Root with filename was treated as archive")
    resolve(single, locator, NS)
    checks += 1

    # Child units alone do not activate the native archive rule.
    root = etree.Element(f"{{{SRC}}}unit", nsmap={None: SRC, "diff": DIFF})
    root.append(etree.fromstring(body.encode()))
    tree = etree.ElementTree(root)
    require(not archive_mode(tree), "Child units incorrectly implied archive")
    full = "/src:unit[1]/src:unit[@filename='a.cpp']/diff:delete[1]/src:expr_stmt[1]"
    resolve(tree, full, NS)
    checks += 1

    # Filename-less archive children retain positional unit segments.
    root.set("url", "synthetic://archive")
    child = root[0]
    child.attrib.pop("filename")
    resolve(tree, "/src:unit[1]/diff:delete[1]/src:expr_stmt[1]", NS)
    checks += 1

    # Full XPath evaluation is required for filenames containing both quotes.
    filename = 'a\'b"c.cpp'
    child.set("filename", filename)
    quoted = "/src:unit[@filename=" + xpath_literal(filename) + "]/diff:delete[1]/src:expr_stmt[1]"
    resolve(tree, quoted, NS)
    checks += 1
    root.append(etree.fromstring(etree.tostring(child)))
    rejects(lambda: resolve(tree, quoted, NS))
    checks += 1

    # Repeated semantic names cannot silently resolve to the first function.
    repeated = parse(f'<unit xmlns="{SRC}" filename="a.cpp"><function><name>f</name></function><function><name>f</name></function></unit>'.encode())
    rejects(lambda: resolve(repeated, "/src:unit[1]/src:function[src:name='f']", NS))
    checks += 1
    rejects(lambda: resolve(single, "/missing:unit[1]", NS))
    checks += 1
    rejects(lambda: resolve(single, locator, {**NS, "diff": "urn:incorrect"}))
    checks += 1

    # One global map cannot resolve the same retained lexical prefix as two URIs.
    collision = parse(f'<unit xmlns="{SRC}" url="synthetic://collision"><unit filename="a.cpp" xmlns:x="urn:first"><x:node/></unit><unit filename="b.cpp" xmlns:x="urn:second"><x:node/></unit></unit>'.encode())
    mapping = {**NS, "x": "urn:first"}
    resolve(collision, "/src:unit[@filename='a.cpp']/x:node[1]", mapping)
    rejects(lambda: resolve(collision, "/src:unit[@filename='b.cpp']/x:node[1]", mapping))
    checks += 1
    return checks


def main():
    directory = Path(__file__).parent / "examples" / "locators"
    manifest = json.loads((directory / "locator-checks.json").read_text())
    require(manifest["convention"] == "srcreader_file_units_v1", "Unknown convention")
    for case in manifest["cases"]:
        check_companions(directory, case, manifest["namespaces"])
        print(f"PASS {case['id']} input and annotated endpoints")
    print(f"PASS {edge_checks()} locator edge cases")


if __name__ == "__main__":
    main()
