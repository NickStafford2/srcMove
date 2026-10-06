"""Read retained detector encodings alongside their before/after source examples.

Case expectations stay in the test. This module supplies inputs, never expected
results; the source projections must continue to describe the retained XML.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
from copy import deepcopy
import re

from tests.support import behavior
from tests.support.annotations import revision_text

ROOT = Path(__file__).resolve().parents[1] / 'fixtures' / 'handwritten'


def source_view(root, revision):
    """Render source with layout, keeping invisible diff details in the XML."""
    root = deepcopy(root)
    src = '{http://www.srcML.org/srcML/src}'
    for function in root.iter(src + 'function'):
        type_node = function.find(src + 'type')
        if type_node is not None and not type_node.tail:
            type_node.tail = ' '
    text = revision_text(root, revision)
    tokens = re.findall(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|#[^\n]*|[^\s{};]+|[{};]', text, re.S)
    lines, current, indent = [], '', 0
    def flush():
        nonlocal current
        if current.strip():
            lines.append('    ' * indent + current.strip())
        current = ''
    for token in tokens:
        if token == '{':
            current += ' {'
            flush()
            indent += 1
        elif token == '}':
            flush()
            indent = max(0, indent - 1)
            current = '}'
            flush()
        elif token == ';':
            current += ';'
            flush()
        elif token.startswith(('//', '#')):
            flush()
            current = token
            flush()
        else:
            current += (' ' if current else '') + token
    flush()
    return '\n'.join(lines) + '\n'


def case_xml(name):
    directory = ROOT / name
    xml = (directory / 'input.srcdiff.xml').read_text()
    root = ET.fromstring(xml)
    for side, revision in (('before', 'delete'), ('after', 'insert')):
        expected = source_view(root, revision)
        if (directory / (side + '.cpp')).read_text() != expected:
            raise ValueError(f'{name}: {side} source view differs from retained encoding')
    return xml


def evaluate_case(testcase, name, *, fragment=False):
    xml = case_xml(name)
    testcase.last_xml = xml
    return behavior.evaluate(testcase, xml, fragment=fragment)


def case_sources(name):
    """Return revision file maps from an ordinary source-generated case."""
    directory = ROOT / name
    revisions = []
    for side in ('before', 'after'):
        root = directory / side
        files = {str(path.relative_to(root)): path.read_text()
                 for path in sorted(root.rglob('*')) if path.is_file()}
        if not files:
            raise ValueError(f'{name}: missing {side} source files')
        revisions.append(files)
    return tuple(revisions)
