"""Protect source review resolution when srcDiff mixes comment revisions."""
import unittest
import xml.etree.ElementTree as ET

from moveSelectionBench.replay_type3_history import resolve_candidates


class HistoricalEndpointResolutionTests(unittest.TestCase):
    def test_opposite_comment_text_does_not_hide_or_invent_endpoint(self):
        tree = ET.ElementTree(ET.fromstring('''
<unit xmlns="http://www.srcML.org/srcML/src" xmlns:diff="http://www.srcML.org/srcDiff">
 <unit filename="same.cpp"><diff:delete><function>int f(){<comment>//<diff:delete>old</diff:delete><diff:insert>new</diff:insert></comment>
return 1;}</function></diff:delete></unit>
</unit>'''))
        candidate = dict(candidate_id=7, side='delete', construct='function',
                         filename='same.cpp', raw_text='int f(){//oldnew\nreturn 1;}',
                         xpath="/src:unit[@filename='same.cpp']/diff:delete[1]/src:function[1]")
        target = dict(construct='function', before_file='same.cpp',
                      before_text='int f(){//old\nreturn 1;}')
        endpoints, methods = resolve_candidates([candidate], tree, target, 'delete', 'before')
        self.assertEqual(endpoints, [candidate])
        self.assertEqual(methods, {'7': 'revision_filtered_xml'})
        for changes in [dict(before_file='unrelated.cpp'),
                        dict(before_text='int f(){//old\nreturn 2;}')]:
            endpoints, methods = resolve_candidates([candidate], tree, target | changes,
                                                    'delete', 'before')
            self.assertEqual((endpoints, methods), ([], {}))
