"""The readability adapter must reject misleading views and wrong occurrences."""
import tempfile
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from tests.support.scenarios import ROOT, MV, NAMESPACES, Scenario, _input_locations, validate_source_views


class ScenarioOracleTests(unittest.TestCase):
    def test_readable_view_cannot_change_statement_order(self):
        """Reject a stationary source example beside XML encoding a genuine reorder."""
        directory = ROOT / 'reorder_with_stationary_repeat'
        xml = (directory / 'input.srcdiff.xml').read_bytes()
        validate_source_views(directory, xml)
        with tempfile.TemporaryDirectory() as temporary:
            changed = Path(temporary)
            (changed / 'before.cpp').write_bytes((directory / 'before.cpp').read_bytes())
            # A stationary after view would contradict the retained reorder XML.
            (changed / 'after.cpp').write_bytes((directory / 'before.cpp').read_bytes())
            with self.assertRaisesRegex(ValueError, 'after.cpp disagrees'):
                validate_source_views(changed, xml)

    def test_wrong_same_text_node_cannot_receive_destination_annotation(self):
        """Reject copy annotations moved from an added call onto an identical continuing call."""
        xml = (ROOT / 'two_existing_calls_two_new_copies' / 'input.srcdiff.xml').read_bytes()
        scenario = Scenario.__new__(Scenario)
        scenario.testcase = self
        scenario.locations = _input_locations(xml)
        origins = scenario._occurrences(['first.repeat_work', 'second.repeat_work'], 'delete')
        destinations = scenario._occurrences(['extra_a.repeat_work', 'extra_b.repeat_work'], 'insert')
        paths = [path for path, _ in origins + destinations]
        scenario.expected_annotations = [('copy', paths)]
        root = ET.fromstring(xml)
        for path in paths:
            root.find('.' + path.removeprefix('/src:unit[1]'), NAMESPACES).set(MV + 'id', 'copy')
        scenario.assert_annotation_locations(ET.tostring(root))
        wanted = destinations[0][0]
        continuing = scenario._occurrences(['first.repeat_work'], 'insert')[0][0]
        root.find('.' + wanted.removeprefix('/src:unit[1]'), NAMESPACES).attrib.pop(MV + 'id')
        root.find('.' + continuing.removeprefix('/src:unit[1]'), NAMESPACES).set(MV + 'id', 'copy')
        with self.assertRaises(AssertionError):
            scenario.assert_annotation_locations(ET.tostring(root))
