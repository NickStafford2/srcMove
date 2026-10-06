"""Source-generated location contracts across controls and archive boundaries.

Expected movement comes from paired source placement. srcDiff may expose the
opposite region of a reorder; these tests accept either genuine displacement,
while separately checking exact-target classification when that pair is exposed.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from benchmarking.tooling import find_srcdiff, find_srcmove
from tests.support.validation import xpaths_to_files

TARGET = 'int target = source + 17;'


def function(body: str) -> str:
    return 'void work() {\n' + body + '\n}\n'


class SourceCorrespondenceVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srcdiff = find_srcdiff(REPO_ROOT, None)
        cls.srcmove = find_srcmove(REPO_ROOT, None)
        if cls.srcdiff is None or cls.srcmove is None:
            raise RuntimeError('srcdiff and srcMove are required for source contracts')

    def evaluate(self, original: dict[str, str], modified: dict[str, str]) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, after = root / 'original', root / 'modified'
            before.mkdir()
            after.mkdir()
            for folder, sources in ((before, original), (after, modified)):
                for name, text in sources.items():
                    path = folder / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)
            xml = root / 'srcdiff.xml'
            completed = subprocess.run(
                [str(self.srcdiff), str(before), str(after), '-o', str(xml)],
                cwd=REPO_ROOT, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            # Parsing also rejects truncated or malformed upstream output.
            ET.parse(xml)
            payloads, annotations = [], []
            for mode in ('ordinary', 'diagnostic', 'results_only'):
                result, output = root / f'{mode}.json', root / f'{mode}.xml'
                command = [str(self.srcmove), str(xml)]
                if mode != 'results_only':
                    command.append(str(output))
                command += ['--results', str(result)]
                if mode != 'ordinary':
                    command.append('--diagnostics')
                if mode == 'results_only':
                    command.append('--results-only')
                completed = subprocess.run(command, cwd=REPO_ROOT,
                                           capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                payloads.append(json.loads(result.read_text()))
                if mode != 'results_only':
                    annotations.append(output.read_bytes())
            self.assertEqual(annotations[0], annotations[1])
            self.assertEqual(payloads[1], payloads[2])
            ordinary = dict(payloads[1])
            ordinary.pop('diagnostics')
            self.assertEqual(ordinary, payloads[0])
            return payloads[1]

    def pair(self, before: str, after: str) -> dict:
        return self.evaluate({'Case.cpp': function(before)},
                             {'Case.cpp': function(after)})

    def target_correspondences(self, payload: dict) -> list[dict]:
        candidates = {item['candidate_id']: item
                      for item in payload['diagnostics']['candidates']}
        return [item for item in payload['diagnostics']['correspondences']
                if candidates[item['delete_candidate_id']]['raw_text'] == TARGET
                and candidates[item['insert_candidate_id']]['raw_text'] == TARGET]

    def assert_displacement(self, payload: dict, *, control_header: str | None = None,
                            control_markers: tuple[str, ...] = (),
                            destination_header: str | None = None):
        def complete_control(text: str, header: str) -> bool:
            return (text.lstrip().startswith(header) and
                    all(marker in text for marker in control_markers))

        matching = []
        for move in payload['moves']:
            origins, destinations = move['from_raw_texts'], move['to_raw_texts']
            exact_target = (any(text.strip() == TARGET for text in origins) and
                            any(text.strip() == TARGET for text in destinations))
            control = (control_header is not None and
                       any(complete_control(text, control_header) for text in origins) and
                       any(complete_control(text, destination_header or control_header)
                           for text in destinations))
            if exact_target or control:
                matching.append(move)
        self.assertTrue(matching,
                        'both selected endpoints must be the target or the complete labeled control')
        for pair in self.target_correspondences(payload):
            self.assertEqual(pair['shadow_change'], 'relocated')

    def test_crossing_unchanged_try_catch_has_relocated_classification(self):
        anchor = 'try { checkpoint(); } catch (...) { recover(); }'
        payload = self.pair(TARGET + '\n' + anchor, anchor + '\n' + TARGET)
        self.assertTrue(self.target_correspondences(payload),
                        'source fixture must expose an exact target pair')
        self.assert_displacement(payload)

    def test_stationary_target_after_try_catch_is_not_a_move(self):
        body = 'try { checkpoint(); } catch (...) { recover(); }\n' + TARGET
        payload = self.pair(body, '// unrelated explanation\n' + body)
        self.assertEqual(payload['moves'], [])

    def test_braced_and_unbraced_loop_and_switch_crossings(self):
        for anchor in (
            'while (ready) { checkpoint(); }',
            'while (ready) checkpoint();',
            'do { checkpoint(); } while (ready);',
            'do checkpoint(); while (ready);',
            'switch (choice) { case 0: checkpoint(); break; default: recover(); break; }',
        ):
            with self.subTest(anchor=anchor):
                self.assert_displacement(self.pair(TARGET + '\n' + anchor,
                                                   anchor + '\n' + TARGET))

    def test_common_control_header_with_edited_body_preserves_displacement(self):
        # Keep the edited region large enough for a meaningful Type-3 comparison
        # if srcDiff exposes the control rather than the exact target statement.
        calls = '\n'.join(f'checkpoint_{index}();' for index in range(20))
        for control in ('if (ready)', 'while (ready)',
                        'for (int i = 0; i < limit; ++i)'):
            with self.subTest(control=control):
                before = TARGET + '\n' + control + ' {\n' + calls + '\n}'
                after = control + ' {\n' + calls + '\nadded();\n}\n' + TARGET
                self.assert_displacement(
                    self.pair(before, after), control_header=control,
                    control_markers=tuple(f'checkpoint_{index}();' for index in range(20)))

    def test_edited_control_header_and_body_preserve_actual_reorder(self):
        calls = '\n'.join(f'checkpoint_{index}();' for index in range(20))
        before = TARGET + '\nif (ready) {\n' + calls + '\n}'
        after = 'if (ready_new) {\n' + calls + '\nadded();\n}\n' + TARGET
        self.assert_displacement(
            self.pair(before, after), control_header='if (ready)',
            destination_header='if (ready_new)', control_markers=tuple(f'checkpoint_{index}();' for index in range(20)))

    def test_added_wrapper_and_sibling_crossing_remain_a_move(self):
        before = TARGET + '\ncheckpoint();'
        after = 'checkpoint();\nif (ready) {\n' + TARGET + '\n}'
        payload = self.pair(before, after)
        self.assertTrue(self.target_correspondences(payload))
        self.assert_displacement(payload)

    def test_removed_wrapper_with_sibling_crossing_remains_a_move(self):
        before = 'if (ready) {\n' + TARGET + '\n}\ncheckpoint();'
        after = 'checkpoint();\n' + TARGET
        payload = self.pair(before, after)
        self.assertTrue(self.target_correspondences(payload))
        self.assert_displacement(payload)

    def test_archive_units_do_not_share_structural_or_anchor_regions(self):
        old = function(TARGET + '\ncheckpoint();')
        new = function('checkpoint();\n' + TARGET)
        isolated = self.evaluate({'A.cpp': old}, {'A.cpp': new})
        secondary = 'int secondary = source + 29;'
        archive = self.evaluate({'A.cpp': old, 'B.cpp': old.replace(TARGET, secondary)},
                                {'A.cpp': new, 'B.cpp': new.replace(TARGET, secondary)})
        candidates = {item['candidate_id']: item
                      for item in archive['diagnostics']['candidates']}
        pairs = [item for item in archive['diagnostics']['correspondences']
                 if item['correspondence_kind'] == 'type1'
                 and candidates[item['delete_candidate_id']]['raw_text']
                     in (TARGET, secondary)
                 and candidates[item['delete_candidate_id']]['raw_text'] ==
                     candidates[item['insert_candidate_id']]['raw_text']]
        self.assertEqual({pair['before_context']['revision_file'] for pair in pairs},
                         {'A.cpp', 'B.cpp'})
        self.assertEqual(archive['move_group_count'], 2)
        expected_files = {TARGET: 'A.cpp', secondary: 'B.cpp'}
        self.assertCountEqual([move['from_raw_texts'] for move in archive['moves']],
                              [[TARGET], [secondary]])
        for move in archive['moves']:
            self.assertEqual(move['content_relationship'], 'type1')
            self.assertEqual(move['to_raw_texts'], move['from_raw_texts'])
            filename = expected_files[move['from_raw_texts'][0]]
            self.assertEqual(xpaths_to_files(move['from_xpaths']), [filename])
            self.assertEqual(xpaths_to_files(move['to_xpaths']), [filename])
        for pair in pairs:
            self.assertEqual(pair['before_context']['revision_file'],
                             pair['after_context']['revision_file'])
            self.assertEqual(pair['before_context']['anchor_region_id'],
                             pair['after_context']['anchor_region_id'])
        for side in ('before_context', 'after_context'):
            by_file = {}
            for pair in pairs:
                by_file.setdefault(pair[side]['revision_file'], set()).add(
                    (pair[side]['structural_region_id'], pair[side]['anchor_region_id']))
            self.assertEqual(len(by_file['A.cpp']), 1)
            self.assertEqual(len(by_file['B.cpp']), 1)
            first = next(iter(by_file['A.cpp']))
            second = next(iter(by_file['B.cpp']))
            self.assertNotEqual(first[0], second[0], 'structural regions must be file-local')
            self.assertNotEqual(first[1], second[1], 'anchor regions must be file-local')
        self.assert_displacement(isolated)


if __name__ == '__main__':
    unittest.main()
