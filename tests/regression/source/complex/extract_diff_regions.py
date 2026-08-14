#!/usr/bin/env python3
# extract_diff_regions.py

import copy
import sys
import xml.etree.ElementTree as ET


SRC_NS = "http://www.srcML.org/srcML/src"
DIFF_NS = "http://www.srcML.org/srcDiff"
MV_NS = "http://www.srcML.org/srcMove"

ET.register_namespace("", SRC_NS)
ET.register_namespace("diff", DIFF_NS)
ET.register_namespace("mv", MV_NS)


def local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def namespace_uri(tag: str) -> str:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ""


def collect_diff_nodes(root: ET.Element):
    out = []
    for elem in root.iter():
        ns = namespace_uri(elem.tag)
        name = local_name(elem.tag)
        if ns == DIFF_NS and name in {"insert", "delete"}:
            out.append(elem)
    return out


def build_output_tree(nodes):
    debug_root = ET.Element("debug_diff_regions")

    summary = ET.SubElement(debug_root, "summary")
    summary.set("count", str(len(nodes)))

    inserts_container = ET.SubElement(debug_root, "inserts")
    deletes_container = ET.SubElement(debug_root, "deletes")
    mixed_container = ET.SubElement(debug_root, "all_regions")

    insert_count = 0
    delete_count = 0

    for idx, node in enumerate(nodes, start=1):
        kind = local_name(node.tag)

        wrapper = ET.Element("region")
        wrapper.set("index", str(idx))
        wrapper.set("kind", kind)

        for attr_name, attr_value in sorted(node.attrib.items()):
            wrapper.set(f"attr_{local_name(attr_name)}", attr_value)

        wrapper.append(copy.deepcopy(node))
        mixed_container.append(wrapper)

        if kind == "insert":
            insert_count += 1
            ins_wrap = ET.Element("region")
            ins_wrap.set("index", str(insert_count))
            for attr_name, attr_value in sorted(node.attrib.items()):
                ins_wrap.set(f"attr_{local_name(attr_name)}", attr_value)
            ins_wrap.append(copy.deepcopy(node))
            inserts_container.append(ins_wrap)

        elif kind == "delete":
            delete_count += 1
            del_wrap = ET.Element("region")
            del_wrap.set("index", str(delete_count))
            for attr_name, attr_value in sorted(node.attrib.items()):
                del_wrap.set(f"attr_{local_name(attr_name)}", attr_value)
            del_wrap.append(copy.deepcopy(node))
            deletes_container.append(del_wrap)

    summary.set("inserts", str(insert_count))
    summary.set("deletes", str(delete_count))

    return ET.ElementTree(debug_root)


def indent(elem, level=0):
    indent_str = "\n" + ("  " * level)
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent_str + "  "
        for child in elem:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent_str
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indent_str


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <input.xml> <output.xml>", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    tree = ET.parse(input_path)
    root = tree.getroot()

    diff_nodes = collect_diff_nodes(root)
    out_tree = build_output_tree(diff_nodes)

    indent(out_tree.getroot())
    out_tree.write(output_path, encoding="utf-8", xml_declaration=True)

    print(f"Wrote {len(diff_nodes)} diff regions to {output_path}")


if __name__ == "__main__":
    main()
