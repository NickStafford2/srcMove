"""Independently check sequence metadata against revision-projected native XML."""
import re
from xml.parsers import expat

SRC = "http://www.srcML.org/srcML/src"
DIFF = "http://www.srcML.org/srcDiff"
CPP = "http://www.srcML.org/srcML/cpp"


def element_positions(xml):
    """Reconstruct srcReader event indices, without calling the producer.

    srcReader emits start/end events (including an end for empty elements),
    emits one event per ASCII whitespace character and per non-whitespace run
    under its current Docker text splitter, plus one per XML comment,
    processing instruction, or CDATA section.
    Expat's arbitrary character callback boundaries must not affect counts.
    """
    parser = expat.ParserCreate()
    positions, pending = [], []
    index = 0
    cdata = False

    def flush():
        nonlocal index
        index += len(re.findall(r"[ \t\r\n\v\f]|[^ \t\r\n\v\f]+", "".join(pending)))
        pending.clear()

    def event(*args):
        nonlocal index
        flush()
        index += 1

    def start(*args):
        flush()
        positions.append(index)
        event()

    def characters(text):
        if not cdata:
            pending.append(text)

    def start_cdata():
        nonlocal cdata
        event()
        cdata = True

    def end_cdata():
        nonlocal cdata
        cdata = False

    parser.StartElementHandler = start
    parser.EndElementHandler = event
    parser.CharacterDataHandler = characters
    parser.CommentHandler = event
    parser.ProcessingInstructionHandler = event
    parser.StartCdataSectionHandler = start_cdata
    parser.EndCdataSectionHandler = end_cdata
    parser.Parse(xml, True)
    return positions


def validate_sequences(xml, tree, payload, resolve, *, check_parent_ids=True):
    """Check actual parents, revision files, sibling positions, order and spans.

    Known diff wrappers are transparent when finding source parents. Comments
    and whitespace disappear; common and unselected source elements still take
    sibling positions. Each non-whitespace source-text run consumes a barrier
    position too. Input stream indices identify parents only, never order.
    Set check_parent_ids=False only for an annotated document when original
    input bytes are unavailable: writer framing may change event indices. Actual
    parent identity, adjacency, file, order and overlap checks still apply.
    """
    from lxml import etree

    items = [item for item in payload["output_items"]
             if item["kind"] == "sequence_move_group"]
    if not items:
        return
    elements = [node for node in tree.iter() if isinstance(node.tag, str)]
    positions = element_positions(xml) if check_parent_ids else []
    if check_parent_ids and len(elements) != len(positions):
        raise ValueError("Sequence XML event inventory differs from parsed elements")
    starts = dict(zip(elements, positions))
    groups = {group["id"]: group for group in payload["atomic_move_groups"]}
    namespaces = payload["xpath_context"]["namespaces"]
    occupied = {"original": set(), "modified": set()}
    occupied_ancestors = {"original": set(), "modified": set()}

    def text_without_comments(node):
        if not isinstance(node.tag, str) or etree.QName(node).localname == "comment":
            return ""
        return (node.text or "") + "".join(
            text_without_comments(child) + (child.tail or "") for child in node)

    for side in ("original", "modified"):
        contexts = {}
        children = {}

        def visit_content(node, unit, parent, state, allowed):
            def text_barriers(text):
                if state in ("both", side):
                    # Match the collector's non-whitespace text events, rather
                    # than treating an entire mixed-content string as one gap.
                    children.setdefault(parent, []).extend(
                        None for _ in re.finditer(r"[^ \t\r\n\v\f]+", text or ""))

            text_barriers(node.text)
            for child in node:
                visit(child, unit, parent, state, allowed)
                # A tail belongs to the enclosing context, including after an
                # ignored comment or an opposite-revision wrapper.
                text_barriers(child.tail)

        def visit(node, unit=None, parent=None, state="both", allowed=True):
            if not isinstance(node.tag, str):
                return
            name = etree.QName(node)
            if name.namespace == SRC and name.localname == "unit":
                unit, parent = node, node
                visit_content(node, unit, parent, state, allowed)
                return
            if name.localname == "comment":
                return
            if name.namespace == DIFF:
                if name.localname == "ws":
                    if text_without_comments(node).strip() and state in ("both", side):
                        children.setdefault(parent, []).append(None)
                    return
                revision = {"delete": "original", "insert": "modified",
                            "common": "both"}.get(name.localname)
                if revision is None:
                    if state in ("both", side):
                        children.setdefault(parent, []).append(None)
                    allowed = False
                else:
                    state = revision
                    allowed = allowed and revision in ("both", side)
                visit_content(node, unit, parent, state, allowed)
                return
            # A source parent absent from this revision hides its descendants,
            # including nested diff:common elements.
            if state not in ("both", side):
                return
            siblings = children.setdefault(parent, [])
            siblings.append(node)
            contexts[node] = (unit, parent, len(siblings), allowed and name.namespace != CPP)
            visit_content(node, unit, node, state, allowed and name.namespace != CPP)

        visit(tree.getroot())
        for item in items:
            label = f"Sequence {item['id']} {side}"
            span = item["sequence"][side]
            members = []
            for group_id in item["member_group_ids"]:
                group = groups[group_id]
                if (group["content_relationship"] != "type1"
                        or group["correspondence"]["status"] != "selected_pair"
                        or len(group[side]) != 1):
                    raise ValueError(f"{label}: member is not a Type-1 selected pair")
                node = resolve(tree, group[side][0]["xpath"], namespaces)
                if node not in contexts or not contexts[node][3]:
                    raise ValueError(f"{label}: member lacks reliable revision structure")
                unit, parent, ordinal, _ = contexts[node]
                filename = unit.get("filename", "")
                revision_file = filename.split("|", 1)[0 if side == "original" else -1]
                if span["revision_file"] != revision_file:
                    raise ValueError(f"{label}: revision file differs from XML")
                kind = "unit" if parent is unit else "element"
                if check_parent_ids:
                    expected_parent = f"{filename}:{side}:{kind}:{starts[parent]}"
                    if span["parent_id"] != expected_parent:
                        raise ValueError(f"{label}: parent ID differs from XML parent")
                members.append((node, parent, ordinal))
            first, last = span["first_child_ordinal"], span["last_child_ordinal"]
            if len(members) < 2 or last - first + 1 != len(members):
                raise ValueError(f"{label}: span length differs from members")
            parent = members[0][1]
            if any(member_parent is not parent for _, member_parent, _ in members):
                raise ValueError(f"{label}: members have different XML parents")
            if [ordinal for _, _, ordinal in members] != list(range(first, last + 1)):
                raise ValueError(f"{label}: child positions or member order differ from XML")
            for node, _, _ in members:
                ancestors = set(node.iterancestors())
                if (node in occupied[side] or node in occupied_ancestors[side]
                        or ancestors.intersection(occupied[side])):
                    raise ValueError(f"{label}: sequence XML spans overlap")
                occupied[side].add(node)
                occupied_ancestors[side].update(ancestors)
