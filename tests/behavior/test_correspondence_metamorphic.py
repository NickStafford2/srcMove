"""Bounded representation changes must preserve independently supported endpoints."""
from collections import Counter
import re
import unittest

from tests.support import behavior as fixture
from tests.behavior.test_partial_correspondence import function, loop


def endpoints(payload, undo=lambda text: text):
    # A group carries its complete endpoint association. Keep duplicates and
    # cardinality; IDs and sequence packaging are deliberately not the oracle.
    return Counter((move['content_relationship'],
                    tuple(sorted((undo(path), undo(text)) for path, text in
                                 zip(move['from_xpaths'], move['from_raw_texts']))),
                    tuple(sorted((undo(path), undo(text)) for path, text in
                                 zip(move['to_xpaths'], move['to_raw_texts']))))
                   for move in payload['moves'])


class CorrespondenceMetamorphicTests(unittest.TestCase):
    def setUp(self):
        a, b, repeat = (fixture.expression(name) for name in
                        ('unique_a', 'unique_b', 'repeat_work'))
        before = [loop([a, b, repeat])]
        after = [loop([a, b, repeat]), loop([repeat], 'extra')]
        self.xml = fixture.PREFIX.replace('before.cpp|after.cpp', 'same.cpp') + function(
            fixture.run('delete', before) + fixture.run('insert', after)) + '</unit>'
        self.original = fixture.evaluate(self, self.xml)
        copies = [move for move in self.original['moves']
                  if move['selection_reason'] == 'continuing_source_copy']
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]['from_raw_texts'], ['repeat_work(state);'])
        self.assertEqual(copies[0]['to_raw_texts'], ['repeat_work(state);'])
        self.assertIn('diff:insert[2]', copies[0]['to_xpaths'][0])

    def assert_equivalent(self, changed, undo=lambda text: text):
        actual = fixture.evaluate(self, changed)
        self.assertEqual(endpoints(actual, undo), endpoints(self.original, undo))
        copies = [move for move in actual['moves']
                  if move['selection_reason'] == 'continuing_source_copy']
        self.assertEqual(len(copies), 1)
        self.assertEqual(len(copies[0]['from_xpaths']), 1)
        self.assertEqual(len(copies[0]['to_xpaths']), 1)

    def test_whitespace_only_xml_text_events_preserve_endpoints(self):
        # Whitespace between source markup has no identifier/operator content.
        self.assert_equivalent(self.xml.replace('><', '> \n\t<'),
                               lambda text: re.sub(r'\s+', '', text))

    def test_comments_inside_both_continuing_regions_do_not_invent_pairs(self):
        comment = '<comment type="block">/* unrelated_name(99); */</comment>'
        changed = self.xml.replace('<block_content>', '<block_content>' + comment)
        self.assert_equivalent(changed)

    def test_consistent_bijective_renaming_preserves_copy_provenance(self):
        names = ('unique_a', 'unique_b', 'repeat_work', 'state', 'keep_running', 'extra')
        changed = self.xml
        for name in names:
            changed = changed.replace('>' + name + '<', '>renamed_' + name + '<')
        self.assert_equivalent(changed, lambda text: text.replace('renamed_', ''))
