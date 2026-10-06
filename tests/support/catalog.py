"""Describe the runner's inventory without running tests or interpreting results."""
import ast
from collections import Counter
from html import escape
import inspect
import json
from pathlib import Path
import sys

from tests.support import fixture_tests, selection_catalog
from tests.support.cases import XmlCaseSpec, SourceCaseSpec, PolicyCaseSpec

ROOT = Path(__file__).resolve().parents[2]
COMPONENT_PURPOSES = {
    'canonical_forms': 'Check exact identity, consistent renaming, literal categories, syntax, transparent wrappers, fragmented names, and member qualifiers.',
    'selection_policy': 'Check proposal ranking, deterministic ties, and when stronger independent children replace a weak parent.',
    'sequence_similarity': 'Accept the 90% Type-3 boundary and reject sequence pairs below it.',
    'shadow_classifier': 'Classify explicit endpoint contexts and preserve diagnostic reasons and move eligibility.',
    'location_context': 'Read named source examples to check revision paths, physical containers, sibling anchors, ancestry, and registry ownership.',
    'shadow_diagnostics': 'Check that diagnostic output preserves ordinary results and exposes wrapped, stationary, and relocated correspondences.',
}


def link(path, label, line=None):
    path = Path(path).resolve()
    return {'label': label, 'path': str(path), 'line': line,
            'url': path.as_uri() + (f'#L{line}' if line else '')}


def source_link(value, label):
    path = inspect.getsourcefile(value)
    _, line = inspect.getsourcelines(value)
    return link(path, label, line)


def _module_files(module):
    """Expose declared file constants, without guessing paths from case names."""
    return sorted({value.resolve() for value in vars(module).values()
                   if isinstance(value, Path) and value.is_file()})


def _catalog_document(path):
    if path.suffix != '.json':
        return None
    document = json.loads(path.read_text())
    cases = document.get('cases') if isinstance(document, dict) else None
    if path.name == 'type2_normalization_contracts.json' and isinstance(document, dict):
        cases = [{'id': name, 'expected': expected} for name, expected in document.items()]
    if not isinstance(cases, list):
        return None
    expanded = []
    for case in cases:
        reference = next((field for field in ('case', 'definition')
                          if isinstance(case, dict) and isinstance(case.get(field), str)), None)
        if reference:
            case_path = (path.parent / case[reference]).resolve()
            definition = json.loads(case_path.read_text())
            expanded.append({'source': link(case_path, case.get('id', case_path.name)),
                             'inputs': _definition_inputs(definition, case_path.parent, path.parent),
                             'definition': definition})
        else:
            expanded.append(case)
    return {'source': link(path, path.name), 'cases': expanded}


def _definition_inputs(definition, directory, catalog_root):
    inputs = [link(path, path.name) for path in sorted(directory.glob('*.cpp')) if path.is_file()]
    for side in ('before', 'after'):
        inputs.extend(link(path, side.title() + ': ' + str(path.relative_to(directory / side)))
                      for path in sorted((directory / side).rglob('*')) if path.is_file())
    inputs.extend(link(path, 'Expected endpoint: ' + path.name)
                  for path in sorted(directory.glob('expected-*')) if path.is_file())

    def references(value):
        if not isinstance(value, dict):
            return
        for field, child in value.items():
            if field in ('input', 'fixture', 'srcdiff', 'source_pair', 'original', 'modified') and isinstance(child, str):
                path = catalog_root / child
                if path.is_file():
                    inputs.append(link(path, 'Canonical input: ' + child))
                elif path.is_dir():
                    inputs.extend(link(file, 'Canonical input: ' + str(file.relative_to(catalog_root)))
                                  for file in sorted(path.rglob('*')) if file.is_file())
            elif isinstance(child, dict):
                references(child)
    references(definition)
    return inputs


def _fixture_links(case):
    if isinstance(case, XmlCaseSpec):
        return [link(case.input_xml, 'Diff input')], [
            link(case.expected_json, 'Expected JSON'), link(case.expected_xml, 'Expected XML')]
    if isinstance(case, SourceCaseSpec):
        inputs = []
        for label, path in [('Before', case.original), ('After', case.modified)]:
            if path.is_dir():
                inputs.extend(link(file, label + ': ' + str(file.relative_to(path)))
                              for file in sorted(path.rglob('*')) if file.is_file())
            else:
                inputs.append(link(path, label))
        return inputs, [link(case.oracle_json, 'Expected result')]
    if isinstance(case, PolicyCaseSpec):
        if 'case_path' in case.definition:
            path = Path(case.definition['case_path'])
            inputs = [link(file, side.title() + ': ' + str(file.relative_to(path.parent / side)))
                      for side in ('before', 'after')
                      for file in sorted((path.parent / side).rglob('*')) if file.is_file()]
            expectations = [link(path, 'Expected policy and purpose')]
            expectations.extend(link(file, 'Expected endpoint: ' + file.name)
                                for file in sorted(path.parent.glob('expected-*')) if file.is_file())
            expectations.append(source_link(fixture_tests.evaluate, 'Policy assertions'))
            return inputs, expectations
        return [link(case.catalog_path, 'Source and rationale catalog')], [
            link(case.catalog_path, 'Expected policy: ' + case.name),
            source_link(fixture_tests.evaluate, 'Policy assertions')]
    raise TypeError(type(case).__name__)


def _scenario_links(method, module):
    """Expose literal scenario fixtures and their actual expectation callbacks."""
    inputs, expectations = [], []
    lines, start = inspect.getsourcelines(method)
    if not any(name + '(' in ''.join(lines) for name in ('load_scenario', 'case_xml', 'evaluate_case')):
        return inputs, expectations
    module_tree = ast.parse(Path(inspect.getsourcefile(method)).read_text())
    tree = next(node for node in ast.walk(module_tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == method.__name__ and start <= node.lineno < start + len(lines))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in ('load_scenario', 'case_xml', 'evaluate_case'):
            ordinal = 0 if node.func.id == 'case_xml' else 1
            if len(node.args) <= ordinal:
                continue
            name = node.args[ordinal]
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                family = 'scenarios' if node.func.id == 'load_scenario' else 'handwritten'
                directory = ROOT / 'tests/fixtures' / family / name.value
                inputs.extend(link(path, str(path.relative_to(directory)))
                              for path in sorted(directory.rglob('*')) if path.is_file())
        callback = None
        if isinstance(node.func, ast.Name) and node.func.id.startswith('expect_'):
            callback = vars(module).get(node.func.id)
        elif isinstance(node.func, ast.Attribute) and node.func.attr.startswith('expect_') and isinstance(node.func.value, ast.Name):
            owner = vars(module).get(node.func.value.id)
            callback = getattr(owner, node.func.attr, None)
        if inspect.isfunction(callback):
            expectations.append(source_link(callback, 'Expected behavior'))
    return inputs, expectations


def describe_test(test):
    method = getattr(test, test._testMethodName)
    module = sys.modules[type(test).__module__]
    suite = ('behavior' if test.id().startswith('fixtures.') else
             'unit' if test.id().startswith('components.') else
             next((part for part in type(test).__module__.split('.')
                   if part in ('behavior', 'unit', 'tooling')), 'unknown'))
    entry = {'id': test.id(), 'suite': suite, 'topic': type(test).__module__.split('.')[-1],
             'purpose': inspect.getdoc(method) or 'needs explanation',
             'context': inspect.getdoc(type(test)) or inspect.getdoc(module) or '',
             'test': source_link(method, 'Test and assertions'),
             'inputs': [], 'expectations': [source_link(method, 'Assertions')],
             'catalogs': []}
    if isinstance(test, fixture_tests.AcceptedFixtureTest):
        case = test.case
        entry['inputs'], entry['expectations'] = _fixture_links(case)
        entry['topic'] = fixture_tests.fixture_kind(case)
        entry['purpose'] = test.shortDescription() or 'needs explanation'
        if isinstance(case, PolicyCaseSpec):
            entry['catalogs'] = [str(case.catalog_path)]
        else:
            description = case.case_dir / 'case.json'
            if description.is_file():
                metadata = json.loads(description.read_text())
                entry['inputs'].insert(0, link(description, 'Purpose and case layout'))
                for field in ('before', 'after'):
                    if field in metadata:
                        path = case.case_dir / metadata[field]
                        if path.is_file() and str(path.resolve()) not in {item['path'] for item in entry['inputs']}:
                            entry['inputs'].append(link(path, field.title()))
        entry['expectations'].append(source_link(fixture_tests.fixture_failures, 'Oracle application'))
    elif isinstance(test, selection_catalog.SelectionCatalogTest):
        case = test.case
        entry['purpose'] = case.get('rationale') or 'needs explanation'
        entry['topic'] = case.get('category', 'selection')
        entry['inputs'] = [link(case['input_path'], 'Diff input')]
        entry['expectations'] = [link(ROOT / 'tests/fixtures/selection/catalog.json', 'Expected case: ' + case['id']),
                                 source_link(selection_catalog.evaluate_results, 'Catalog assertions')]
        document = json.loads((ROOT / 'tests/fixtures/selection/catalog.json').read_text())
        reference = next(item for item in document['cases'] if item['id'] == case['id'])
        if 'definition' in reference:
            path = ROOT / 'tests/fixtures/selection' / reference['definition']
            entry['inputs'].extend(_definition_inputs(case, path.parent, ROOT / 'tests/fixtures/selection'))
            entry['expectations'].insert(0, link(path, 'Independent case expectations'))
        entry['expected'] = {field: case[field] for field in ('required', 'forbidden')}
        entry['catalogs'] = [str(ROOT / 'tests/fixtures/selection/catalog.json')]
    elif test.id().startswith('components.'):
        component_paths = {
            'canonical_forms': 'canonical/test_canonical_forms.cpp',
            'selection_policy': 'selection_policy/test_selection_policy.cpp',
            'sequence_similarity': 'sequence_similarity/test_sequence_similarity.cpp',
            'shadow_classifier': 'shadow_classifier/test_shadow_classifier.cpp',
            'location_context': 'location_context/test_location_context.cpp',
            'shadow_diagnostics': 'shadow_classifier/check_shadow_diagnostics.py',
        }
        entry['topic'] = test.name
        path = ROOT / 'tests/unit' / component_paths[test.name]
        lines = path.read_text().splitlines()
        entry['expectations'] = [link(path, 'Component assertions', next(
            index for index, text in enumerate(lines, 1) if text.startswith(('int main(', 'def check_output_equivalence('))))]
        entry['purpose'] = COMPONENT_PURPOSES[test.name]
        entry['context'] = '\n'.join(text.strip()[3:] for text in lines if text.startswith('    // '))
        if test.name == 'shadow_diagnostics':
            entry['expectations'].append(link(path, 'Correspondence expectations', next(
                index for index, text in enumerate(lines, 1) if text.startswith('def check_correspondence_evidence('))))
        if test.name in ('location_context', 'shadow_diagnostics'):
            entry['inputs'] = [link(ROOT / 'tests/unit/location_context/semantic_containers.xml', 'Semantic containers')]
    else:
        scenario_inputs, scenario_expectations = _scenario_links(method, module)
        entry['inputs'].extend(scenario_inputs)
        entry['expectations'].extend(scenario_expectations)
        for path in _module_files(module):
            catalog = _catalog_document(path)
            if catalog:
                entry['catalogs'].append(str(path))
            entry['inputs'].append(link(path, 'Declared fixture: ' + path.name))
        # An author may declare per-method links rather than relying on constants.
        metadata = getattr(test, 'CASE_FILES', {}).get(test._testMethodName, {})
        for field in ('inputs', 'expectations'):
            entry[field].extend(link(ROOT / path, label) for label, path in metadata.get(field, []))
        if not entry['inputs']:
            entry['inputs'] = [link(inspect.getsourcefile(method), 'Inputs and setup in test module')]
    return entry


def build_catalog(tests=None):
    if tests is None:
        from tests.run import inventory
        tests = inventory()
    entries = [describe_test(test) for test in tests]
    ids = [entry['id'] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate inventory IDs')
    catalog_paths = {path for entry in entries for path in entry['catalogs']}
    # Classifier tests also load catalogs through local Path expressions. List
    # those checked-in reference documents without inventing per-method coverage.
    catalog_paths.update(str(path) for path in (ROOT / 'tests/fixtures/selection').glob('*.json')
                         if _catalog_document(path) is not None)
    catalog_paths = sorted(catalog_paths)
    return {'entries': entries, 'counts': dict(Counter(entry['suite'] for entry in entries)),
            'catalogs': [_catalog_document(Path(path)) for path in catalog_paths]}


def _links(links):
    return ' · '.join(f'<a href="{escape(item["url"], quote=True)}">{escape(item["label"])}</a>'
                      for item in links)


def _preview_text(text):
    lines = text.splitlines()
    shown = '\n'.join(lines[:100])
    if len(lines) > 100:
        shown += f'\n\n[Preview truncated: showing 100 of {len(lines)} lines. Open the linked file for the complete input or expectation.]'
    return '<pre>' + escape(shown) + '</pre>'


def _previews(links):
    """Read only accepted fixture files, never arbitrary module paths or XML."""
    source_extensions = {'.cpp', '.c', '.cc', '.cxx', '.h', '.hpp', '.java', '.cs', '.txt'}
    previews, seen = [], set()
    fixture_root = ROOT / 'tests/fixtures'
    for item in links:
        path = Path(item['path']).resolve()
        if path in seen or not path.is_file() or not path.is_relative_to(fixture_root):
            continue
        seen.add(path)
        if path.suffix in source_extensions:
            text = path.read_text()
        elif path.suffix == '.json':
            document = json.loads(path.read_text())
            if not isinstance(document, dict) or 'cases' in document:
                continue
            fields = ('expect', 'required', 'forbidden', 'move_count', 'move_group_count',
                      'move_pair_count', 'move_sequences', 'expected_shadow',
                      'expected_type1_output', 'expected_edges', 'edges')
            expected = {field: document[field] for field in fields if field in document}
            if 'moves' in document:
                expected['moves'] = [{key: move[key] for key in ('content_relationship', 'selection_reason',
                                      'from_raw_texts', 'to_raw_texts') if key in move}
                                     for move in document['moves']]
            if not expected:
                continue
            text = json.dumps(expected, indent=2)
        else:
            continue
        previews.append('<details><summary>' + _links([item]) + '</summary>' + _preview_text(text) + '</details>')
    return ''.join(previews)


def render_html(catalog):
    suites = sorted(catalog['counts'])
    topics = sorted({entry['topic'] for entry in catalog['entries']})
    cards = []
    for entry in catalog['entries']:
        details = ('<p>Context: ' + escape(entry['context']) + '</p>') if entry['context'] else ''
        if entry.get('expected'):
            details += '<pre>' + escape(json.dumps(entry['expected'], indent=2)) + '</pre>'
        if entry['catalogs']:
            details += '<p>Catalog entries shown below are reference material, not additional test IDs.</p>'
        cards.append(f'<article data-suite="{escape(entry["suite"], quote=True)}" data-topic="{escape(entry["topic"], quote=True)}">'
                     f'<h2>{escape(entry["purpose"])}</h2><small>{escape(entry["id"])}</small>'
                     f'<p>{_links([entry["test"]])}</p><p>Input: {_links(entry["inputs"])}</p>'
                     + _previews(entry['inputs']) + f'<p>Expected: {_links(entry["expectations"])}</p>'
                     + _previews(entry['expectations'])
                     + f'<details><summary>Context and expected data</summary>{details}</details></article>')
    references = []
    for document in catalog['catalogs']:
        cases = []
        for case in document['cases']:
            if isinstance(case, dict) and 'source' in case and 'definition' in case:
                definition = case['definition']
                description = definition.get('purpose') or definition.get('rationale') or ''
                context = definition.get('provenance', {}).get('derivation', '')
                cases.append('<section><h3>' + escape(definition.get('id', case['source']['label'])) + '</h3><p>'
                             + escape(description or context) + '</p><p>' + _links([case['source'], *case['inputs']])
                             + '</p>' + _previews(case['inputs']) + _preview_text(json.dumps(definition, indent=2)) + '</section>')
            else:
                cases.append('<pre>' + escape(json.dumps(case, indent=2)) + '</pre>')
        references.append('<details><summary>Catalog: ' + _links([document['source']]) + '</summary>'
                          + ''.join(cases) + '</details>')
    options = lambda values: '<option value="">All</option>' + ''.join(
        f'<option value="{escape(value, quote=True)}">{escape(value)}</option>' for value in values)
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><title>srcMove test catalog</title>
<style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem}article{border-top:1px solid #bbb;padding:1rem 0}h2{font-size:1rem;overflow-wrap:anywhere}pre{white-space:pre-wrap}input,select{padding:.5rem;margin-right:.5rem}a{color:#1464b5}details{margin:.5rem 0}</style>
<h1>srcMove correctness tests</h1><p>One entry per discovered test ID. This page describes inputs and assertions; it does not run tests or report detector outcomes. Missing descriptions remain visible as “needs explanation”. File links open the owning source; #L identifies the source line.</p>
''' + f'<p>{len(catalog["entries"])} test entries; {escape(str(catalog["counts"]))}</p>' + '''
<label>Search <input id="search" type="search"></label><label>Suite <select id="suite">''' + options(suites) + '''</select></label><label>Topic <select id="topic">''' + options(topics) + '''</select></label><p id="visible"></p>
''' + '\n'.join(cards) + '<h2>Catalog reference entries</h2><p>These entries are not added to the discovered test count. A Python test may iterate over several of them.</p>' + '\n'.join(references) + '''
<script>const cards=[...document.querySelectorAll('article')];function filter(){const q=document.getElementById('search').value.toLowerCase(),s=document.getElementById('suite').value,t=document.getElementById('topic').value;let n=0;for(const card of cards){card.hidden=!(card.textContent.toLowerCase().includes(q)&&(!s||card.dataset.suite===s)&&(!t||card.dataset.topic===t));if(!card.hidden)n++;}document.getElementById('visible').textContent=n+' entries shown';}for(const id of ['search','suite','topic'])document.getElementById(id).addEventListener('input',filter);filter();</script></html>'''
