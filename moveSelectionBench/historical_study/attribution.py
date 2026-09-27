"""Conservative source-oracle attribution, independent of detector decisions.

Public functions return JSON-safe dictionaries. Pass the full Git source text
(decoded as UTF-8 WITHOUT newline translation), an ElementTree/root, and either
schema-4 diagnostics or a results object containing ``diagnostics``. No text-only
fallback establishes identity: repeated occurrences require source positions.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET

SRC = 'http://www.srcML.org/srcML/src'
DIFF = 'http://www.srcML.org/srcDiff'
POS = 'http://www.srcML.org/srcML/position'
NS = {'src': SRC, 'diff': DIFF, 'pos': POS, 'cpp': 'http://www.srcML.org/srcML/cpp'}
SIDES = ('delete', 'insert')


def _lf(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _trivia(text):
    """Only whitespace/comments outside a proven XML construct are ignorable."""
    return not re.sub(r'/\*[\s\S]*?\*/|//[^\n]*', '', text).strip()


def _filename(filename, side):
    parts = filename.split('|')
    if len(parts) == 1:
        return filename
    return parts[0 if side == 'delete' else -1] if len(parts) == 2 else None


def _projection(unit, side):
    """Project nested revision overrides and retain exact source character spans."""
    chunks, spans, cursor = [], {}, 0

    def visit(node, state='common', comment=False):
        nonlocal cursor
        if node.tag in ('{' + DIFF + '}' + name for name in (*SIDES, 'common')):
            state = node.tag.rsplit('}', 1)[-1]
        comment = comment or node.tag == '{' + SRC + '}comment'
        start, owners = cursor, set()

        def emit(text):
            nonlocal cursor
            text = _lf(text or '')
            if text.strip() and not comment:
                owners.add(state)
            if state in ('common', side):
                chunks.append(text)
                cursor += len(text)

        emit(node.text)
        for child in node:
            owners.update(visit(child, state, comment))
            emit(child.tail)
        spans[id(node)] = (start, cursor, owners)
        return owners

    visit(unit)
    return ''.join(chunks), spans


def revision_text(node, side, membership='common'):
    """Project a subtree; caller may supply its inherited revision state."""
    if side not in SIDES:
        raise ValueError('side must be delete or insert')
    state = node.tag.rsplit('}', 1)[-1] if node.tag in {
        '{' + DIFF + '}' + name for name in (*SIDES, 'common')
    } else membership
    result = _lf(node.text or '') if state in ('common', side) else ''
    for child in node:
        result += revision_text(child, side, state)
        if state in ('common', side):
            result += _lf(child.tail or '')
    return result


def _xpath_nodes(root, xpath):
    """Resolve the ElementTree XPath subset emitted in diagnostic paths.

    Both archive-relative and root-inclusive paths occur in replay adapters.
    A temporary wrapper permits root-inclusive evaluation without rewriting
    filename/name predicates (whose values may themselves contain slashes).
    Unsupported XPath syntax remains unresolved; there is no text fallback.
    """
    if not isinstance(xpath, str) or not xpath.startswith('/'):
        return []
    wrapper = ET.Element('_attribution_root')
    wrapper.append(root)
    try:
        nodes = root.findall('.' + xpath, NS)
        nodes += wrapper.findall('.' + xpath, NS)
    except (SyntaxError, KeyError, TypeError, ValueError):
        return []
    return list({id(node): node for node in nodes}.values())


def _position_span(node, side, source):
    values = []
    starts = [0] + [m.end() for m in re.finditer('\n', source)]
    for name in ('start', 'end'):
        value = node.get('{' + POS + '}' + name)
        if value is None:
            return None
        parts = value.split('|')
        if len(parts) == 2:
            value = parts[0 if side == 'delete' else 1]
        elif len(parts) != 1:
            return None
        match = re.fullmatch(r'(\d+):(\d+)', value)
        if not match:
            return None
        line, column = map(int, match.groups())
        if not 1 <= line <= len(starts) or column < 1:
            return None
        values.append(starts[line-1] + column - 1)
    return values[0], values[1] + 1  # srcML positions are inclusive


def resolve_endpoint(endpoint, source_text, tree, diagnostics, side):
    """Locate an entire frozen endpoint, never a merely overlapping descendant.

    ``status`` is resolved, absent, or unresolved. ``whole_exposed`` is true,
    false, or null; false is asserted only after exact full-file reconstruction.
    Candidate IDs resolve through their XML XPath, not raw-text similarity.
    """
    if side not in SIDES:
        raise ValueError('side must be delete or insert')
    result = dict(status='unresolved', whole_exposed=None, candidate_ids=[],
                  candidate_available=None, ambiguous_occurrence=False, reason='')
    raw_lines = source_text.splitlines(keepends=True)
    first, last = endpoint['start_line'], endpoint['end_line']
    if not 1 <= first <= last <= len(raw_lines):
        result['reason'] = 'invalid_source_range'
        return result
    raw = ''.join(raw_lines[first-1:last])
    if hashlib.sha256(raw.encode('utf-8')).hexdigest() != endpoint['text_sha256']:
        result['reason'] = 'source_hash_mismatch_or_newline_translation'
        return result
    source = _lf(source_text)
    start = len(_lf(''.join(raw_lines[:first-1])))
    end = start + len(_lf(raw))
    root = tree.getroot() if isinstance(tree, ET.ElementTree) else tree
    units = [node for node in root.iter('{' + SRC + '}unit')
             if node.get('filename') is not None
             and _filename(node.get('filename'), side) == endpoint['path']]
    if len(units) != 1:
        result['ambiguous_occurrence'] = len(units) > 1
        result['reason'] = 'source_unit_missing_or_ambiguous'
        return result
    unit = units[0]
    projected, spans = _projection(unit, side)
    reconstructed = projected == source
    exact_nodes, exposed_nodes = set(), set()
    positions = set()
    for node in unit.iter():
        if node is unit or node.tag == '{' + SRC + '}comment':
            continue
        a, b, owners = spans[id(node)]
        if reconstructed:
            text = projected[a:b]
        else:
            pos = _position_span(node, side, source)
            if pos is None:
                continue
            text = projected[a:b]
            a, b = pos
            if not 0 <= a < b <= len(source) or source[a:b] != text:
                continue
        if not (start <= a < b <= end) or not text.strip():
            continue
        if not _trivia(source[start:a]) or not _trivia(source[b:end]):
            continue
        exact_nodes.add(id(node))
        positions.add((a, b))
        if owners == {side}:
            exposed_nodes.add(id(node))
    # Nested wrappers and structural nodes with identical spans are aliases,
    # not different source occurrences. Nonidentical proven spans are ambiguous.
    if len(positions) > 1:
        core_start, core_end = min(positions, key=lambda span: span[1] - span[0])
        aliases = all(a <= core_start <= core_end <= b
                      and _trivia(source[a:core_start])
                      and _trivia(source[core_end:b]) for a, b in positions)
        if not aliases:
            result['ambiguous_occurrence'] = True
            result['reason'] = 'multiple_whole_source_spans'
            return result
    if not exact_nodes:
        result['status'] = 'absent' if reconstructed else 'unresolved'
        result['whole_exposed'] = False if reconstructed else None
        result['reason'] = 'no_whole_xml_construct' if reconstructed else 'source_reconstruction_mismatch_no_verified_position'
        return result
    result['status'] = 'resolved'
    result['whole_exposed'] = bool(exposed_nodes)
    result['reason'] = 'full_source_reconstruction' if reconstructed else 'verified_revision_position'
    diag = diagnostics.get('diagnostics', diagnostics) if isinstance(diagnostics, dict) else {}
    if not isinstance(diag.get('candidates'), list):
        result['reason'] += ';diagnostic_candidates_unavailable'
        return result
    unresolved_xpath = False
    for candidate in diag['candidates']:
        if candidate.get('side') != side or _filename(candidate.get('filename', ''), side) != endpoint['path']:
            continue
        nodes = _xpath_nodes(root, candidate.get('xpath'))
        if not nodes:
            unresolved_xpath = True
        matching = [node for node in nodes if id(node) in exact_nodes]
        if len(nodes) == 1 and matching:
            result['candidate_ids'].append(candidate['candidate_id'])
        elif matching:
            unresolved_xpath = True
    result['candidate_ids'] = sorted(set(result['candidate_ids']))
    result['candidate_available'] = bool(result['candidate_ids']) if not unresolved_xpath or result['candidate_ids'] else None
    if unresolved_xpath:
        result['reason'] += ';some_candidate_xpaths_unresolved'
    return result


def attribute_event(event, old_source, new_source, tree, diagnostics):
    """Return conservative limiting-stage evidence for one frozen source pair."""
    old = resolve_endpoint(event['old'], old_source, tree, diagnostics, 'delete')
    new = resolve_endpoint(event['new'], new_source, tree, diagnostics, 'insert')
    result = dict(old=old, new=new, limiting_stage='unresolved', selected=None, correspondences=[])
    if any(item['status'] == 'unresolved' for item in (old, new)):
        return result
    if any(item['whole_exposed'] is False for item in (old, new)):
        result['limiting_stage'] = 'whole_endpoint_not_exposed'
        return result
    if any(item['candidate_available'] is None for item in (old, new)):
        return result
    if any(item['candidate_available'] is False for item in (old, new)):
        result['limiting_stage'] = 'candidate_filtering'
        return result
    diag = diagnostics.get('diagnostics', diagnostics)
    if not isinstance(diag.get('correspondences'), list):
        return result
    records = [record for record in diag['correspondences']
               if record.get('delete_candidate_id') in old['candidate_ids']
               and record.get('insert_candidate_id') in new['candidate_ids']]
    result['correspondences'] = records
    if not records:
        result['limiting_stage'] = 'correspondence_unresolved_or_not_recorded'
    elif any(record.get('current_result') == 'move' for record in records):
        result.update(limiting_stage='selected', selected=True)
    elif all(record.get('current_result') == 'not_move' for record in records):
        result['selected'] = False
        result['limiting_stage'] = ('selection' if any(record.get('shadow_change') == 'relocated' for record in records)
                                   else 'location_or_parent_carrying')
    return result
