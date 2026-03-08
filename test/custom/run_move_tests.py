#!/usr/bin/env python3
# run_move_tests.py

import json
import subprocess
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


DIFF_NS = "http://www.srcML.org/srcDiff"
MV_NS = "http://www.srcML.org/srcMove"

NS = {
    "diff": DIFF_NS,
    "mv": MV_NS,
}


def find_diff_nodes(root: ET.Element):
    inserts = root.findall(".//diff:insert", NS)
    deletes = root.findall(".//diff:delete", NS)
    return inserts, deletes


def get_attr(elem: ET.Element, ns: str, local: str):
    return elem.attrib.get(f"{{{ns}}}{local}")


def split_partners(value: str):
    if not value:
        return []
    return [part for part in value.split(";") if part]


def analyze_output_xml(xml_path: Path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    inserts, deletes = find_diff_nodes(root)
    all_nodes = deletes + inserts

    annotated_deletes = 0
    annotated_inserts = 0
    partner_attr_count = 0
    partners_attr_count = 0

    delete_partner_sizes = []
    insert_partner_sizes = []

    for elem in deletes:
        has_move = (
            elem.attrib.get("move") is not None
            or get_attr(elem, MV_NS, "move") is not None
        )
        if has_move:
            annotated_deletes += 1

        partner = get_attr(elem, MV_NS, "partner")
        partners = get_attr(elem, MV_NS, "partners")

        if partner is not None:
            partner_attr_count += 1
            delete_partner_sizes.append(1)
        elif partners is not None:
            partners_attr_count += 1
            delete_partner_sizes.append(len(split_partners(partners)))

    for elem in inserts:
        has_move = (
            elem.attrib.get("move") is not None
            or get_attr(elem, MV_NS, "move") is not None
        )
        if has_move:
            annotated_inserts += 1

        partner = get_attr(elem, MV_NS, "partner")
        partners = get_attr(elem, MV_NS, "partners")

        if partner is not None:
            partner_attr_count += 1
            insert_partner_sizes.append(1)
        elif partners is not None:
            partners_attr_count += 1
            insert_partner_sizes.append(len(split_partners(partners)))

    return {
        "total_inserts": len(inserts),
        "total_deletes": len(deletes),
        "annotated_inserts": annotated_inserts,
        "annotated_deletes": annotated_deletes,
        "partner_attr_count": partner_attr_count,
        "partners_attr_count": partners_attr_count,
        "delete_partner_sizes": delete_partner_sizes,
        "insert_partner_sizes": insert_partner_sizes,
        "total_diff_nodes": len(all_nodes),
    }


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def compare_scalar(actual, expected, key, failures):
    if actual != expected:
        failures.append(f"{key}: expected {expected!r}, got {actual!r}")


def compare_list(actual, expected, key, failures, sort_before_compare=False):
    a = list(actual)
    e = list(expected)
    if sort_before_compare:
        a = sorted(a)
        e = sorted(e)
    if a != e:
        failures.append(f"{key}: expected {e!r}, got {a!r}")


def check_expected(summary_json, xml_analysis, expected):
    failures = []

    summary_checks = {
        "move_count": summary_json.get("move_count"),
        "annotated_regions": summary_json.get("annotated_regions"),
        "regions_total": summary_json.get("regions_total"),
        "candidates_total": summary_json.get("candidates_total"),
        "groups_total": summary_json.get("groups_total"),
    }

    for key, actual_value in summary_checks.items():
        if key in expected:
            compare_scalar(actual_value, expected[key], key, failures)

    xml_checks = {
        "total_inserts": xml_analysis["total_inserts"],
        "total_deletes": xml_analysis["total_deletes"],
        "annotated_inserts": xml_analysis["annotated_inserts"],
        "annotated_deletes": xml_analysis["annotated_deletes"],
        "partner_attr_count": xml_analysis["partner_attr_count"],
        "partners_attr_count": xml_analysis["partners_attr_count"],
        "total_diff_nodes": xml_analysis["total_diff_nodes"],
    }

    for key, actual_value in xml_checks.items():
        if key in expected:
            compare_scalar(actual_value, expected[key], key, failures)

    if "delete_partner_sizes" in expected:
        compare_list(
            xml_analysis["delete_partner_sizes"],
            expected["delete_partner_sizes"],
            "delete_partner_sizes",
            failures,
            sort_before_compare=True,
        )

    if "insert_partner_sizes" in expected:
        compare_list(
            xml_analysis["insert_partner_sizes"],
            expected["insert_partner_sizes"],
            "insert_partner_sizes",
            failures,
            sort_before_compare=True,
        )

    return failures


def run_case(srcmove_path: Path, xml_file: Path, out_dir: Path):
    base = xml_file.stem
    out_xml = out_dir / f"{base}.out.xml"
    out_json = out_dir / f"{base}.results.json"

    cmd = [
        str(srcmove_path),
        str(xml_file),
        str(out_xml),
        "--results",
        str(out_json),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc, out_xml, out_json


def main():
    cwd = Path.cwd()
    out_dir = cwd / "test_out"

    if len(sys.argv) > 1:
        srcmove_path = Path(sys.argv[1]).resolve()
    else:
        srcmove_path = Path("./build/srcMove").resolve()

    if not srcmove_path.exists():
        print(f"error: srcMove not found at {srcmove_path}", file=sys.stderr)
        sys.exit(2)

    out_dir.mkdir(exist_ok=True)

    xml_files = sorted(p for p in cwd.glob("*.xml") if not p.name.endswith(".out.xml"))

    if not xml_files:
        print("No .xml test files found in current directory.")
        sys.exit(0)

    total = 0
    passed = 0
    failed = 0
    skipped = 0

    for xml_file in xml_files:
        total += 1
        expected_path = xml_file.with_suffix(".expected.json")

        if not expected_path.exists():
            print(f"SKIP  {xml_file.name}  (missing {expected_path.name})")
            skipped += 1
            continue

        proc, out_xml, out_json = run_case(srcmove_path, xml_file, out_dir)

        if proc.returncode != 0:
            print(f"FAIL  {xml_file.name}")
            print(f"  srcMove exited with {proc.returncode}")
            if proc.stdout.strip():
                print("  stdout:")
                for line in proc.stdout.strip().splitlines():
                    print(f"    {line}")
            if proc.stderr.strip():
                print("  stderr:")
                for line in proc.stderr.strip().splitlines():
                    print(f"    {line}")
            failed += 1
            continue

        if not out_xml.exists():
            print(f"FAIL  {xml_file.name}")
            print("  missing output xml")
            failed += 1
            continue

        if not out_json.exists():
            print(f"FAIL  {xml_file.name}")
            print("  missing output results json")
            failed += 1
            continue

        try:
            expected = load_json(expected_path)
            summary_json = load_json(out_json)
            xml_analysis = analyze_output_xml(out_xml)
            failures = check_expected(summary_json, xml_analysis, expected)
        except Exception as e:
            print(f"FAIL  {xml_file.name}")
            print(f"  exception while validating: {e}")
            failed += 1
            continue

        if failures:
            print(f"FAIL  {xml_file.name}")
            for msg in failures:
                print(f"  - {msg}")
            failed += 1
        else:
            print(f"PASS  {xml_file.name}")
            passed += 1

    print()
    print(f"total={total} passed={passed} failed={failed} skipped={skipped}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
