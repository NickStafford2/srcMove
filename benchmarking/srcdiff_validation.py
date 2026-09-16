"""Structural admission for srcDiff XML benchmark artifacts."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from benchmarking.contracts import XmlStatus
from benchmarking.provenance import observe_file


SRCML_NAMESPACE = "http://www.srcML.org/srcML/src"
SRCDIFF_NAMESPACES = {
    "http://www.srcML.org/srcDiff",
    "http://www.srcML.org/srcDiff/diff",
}


def validate_srcdiff_xml(path: Path, expected_shape: str) -> dict[str, Any]:
    """Perform generic structural admission without dataset semantics."""

    artifact = observe_file(path)
    if artifact["status"] != "observed":
        return {"status": XmlStatus.MISSING.value}
    base = {
        "size_bytes": artifact["size_bytes"],
        "sha256": artifact["sha256"],
    }
    if artifact["size_bytes"] == 0:
        return {"status": XmlStatus.EMPTY.value, **base}

    namespaces = set()
    try:
        parsed = ET.iterparse(path, events=("start-ns",))
        for _, namespace in parsed:
            namespaces.add(namespace[1])
        root = parsed.root
    except (ET.ParseError, OSError) as error:
        return {
            "status": XmlStatus.MALFORMED.value,
            "error": str(error),
            **base,
        }

    if root.tag != f"{{{SRCML_NAMESPACE}}}unit":
        return {
            "status": XmlStatus.INVALID_STRUCTURE.value,
            "error": "root must be a srcML unit element",
            **base,
        }
    if not namespaces.intersection(SRCDIFF_NAMESPACES):
        return {
            "status": XmlStatus.INVALID_STRUCTURE.value,
            "error": "srcDiff namespace declaration is missing",
            **base,
        }

    child_units = [
        child for child in root if child.tag == f"{{{SRCML_NAMESPACE}}}unit"
    ]
    if expected_shape == "archive" and not child_units:
        return {
            "status": XmlStatus.INVALID_STRUCTURE.value,
            "error": "archive output must contain child unit elements",
            **base,
        }
    if expected_shape == "single_file" and child_units:
        return {
            "status": XmlStatus.INVALID_STRUCTURE.value,
            "error": "single-file output must not contain child unit elements",
            **base,
        }
    if expected_shape not in {"archive", "single_file"}:
        raise ValueError(f"unknown srcDiff XML shape: {expected_shape}")
    return {"status": XmlStatus.VALID.value, **base}
