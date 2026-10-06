"""Load case-directory definitions without changing their independent oracles.

Catalog files list membership. Each referenced case keeps its reviewed fields;
fixture paths remain relative to the catalog's directory, as before migration.
"""
import json
from pathlib import Path


def load_contract_catalog(path):
    path = Path(path)
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or not isinstance(document.get('cases'), list):
        return document
    cases = []
    for reference in document['cases']:
        if isinstance(reference, dict) and 'definition' in reference:
            if set(reference) != {'id', 'definition'}:
                raise ValueError(f'{path}: case reference must contain only id and definition')
            relative = reference['definition']
            if not isinstance(relative, str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
                raise ValueError(f'{path}: unsafe case definition {relative!r}')
            definition = (path.parent / relative).resolve()
            if not definition.is_relative_to(path.parent.resolve()):
                raise ValueError(f'{path}: case definition escapes the catalog')
            case = json.loads(definition.read_text())
            if not isinstance(case, dict) or case.get('id') != reference['id']:
                raise ValueError(f'{definition}: id disagrees with its catalog')
            fixture = case.get('fixture')
            source = case.get('input')
            if isinstance(fixture, str):
                source = fixture
            elif isinstance(fixture, dict):
                source = fixture.get('srcdiff')
            if source is not None:
                import xml.etree.ElementTree as ET
                from tests.support.readable_cases import source_view
                tree = ET.parse(path.parent / source).getroot()
                for side, revision in (('before', 'delete'), ('after', 'insert')):
                    view = definition.parent / (side + '.cpp')
                    if view.read_text() != source_view(tree, revision):
                        raise ValueError(f'{definition}: {side} view differs from the retained input')
            cases.append(case)
        else:
            cases.append(reference)
    return {**document, 'cases': cases}
