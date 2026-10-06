"""Check atomic annotation occurrences against the exported endpoint records."""
from collections import Counter
import xml.etree.ElementTree as ET

MV = "{http://www.srcML.org/srcMove}"
DIFF = "{http://www.srcML.org/srcDiff}"


def revision_text(node: ET.Element, side: str, inherited: str = "common") -> str:
    state = node.tag[len(DIFF):] if node.tag in {
        DIFF + "delete", DIFF + "insert", DIFF + "common"
    } else inherited
    text = (node.text or "") if state in ("common", side) else ""
    for child in node:
        text += revision_text(child, side, state)
        if state in ("common", side):
            text += child.tail or ""
    return text


def validate_annotations(xml: str, moves: list[dict]) -> None:
    """Raise on missing, duplicate, wrong-side, wrong-text or mislinked endpoints.

    Links are compared as multisets. Own paths remain checked by the JSON oracle;
    this check adds the independent XML side/text/link occurrence contract.
    """
    expected = Counter()
    for move in moves:
        for side, other in (("from", "to"), ("to", "from")):
            paths, texts = move[side + "_xpaths"], move[side + "_raw_texts"]
            if len(paths) != len(texts):
                raise AssertionError("endpoint XPath/raw-text lengths differ")
            partners = tuple(sorted(move[other + "_xpaths"]))
            for text in texts:
                expected[(move["move_id"], side, text.strip(), partners)] += 1
    actual = Counter()

    def visit(node: ET.Element, inherited: str = "common") -> None:
        state = node.tag[len(DIFF):] if node.tag in {
            DIFF + "delete", DIFF + "insert", DIFF + "common"
        } else inherited
        move_id = node.get(MV + "id")
        if move_id is not None:
            to_link, from_link = node.get(MV + "to"), node.get(MV + "from")
            if (to_link is None) == (from_link is None):
                raise AssertionError("annotation must have exactly one endpoint link")
            side = "from" if to_link is not None else "to"
            revision = "delete" if side == "from" else "insert"
            link = to_link if to_link is not None else from_link
            if not link:
                raise AssertionError("annotation endpoint link is empty")
            if state != revision:
                raise AssertionError("annotation link contradicts revision ownership")
            actual[(move_id, side, revision_text(node, revision, state).strip(),
                    tuple(sorted(link.split(" | "))))] += 1
        for child in node:
            visit(child, state)

    visit(ET.fromstring(xml))
    if actual != expected:
        raise AssertionError(f"annotation endpoint mismatch: missing={expected - actual}, extra={actual - expected}")
