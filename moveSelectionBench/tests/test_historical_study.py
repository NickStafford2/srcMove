"""Evidence scoring must reject wrong identities and descendant substitutes."""
import unittest
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

from moveSelectionBench.historical_study.study import (
    match_event, xpath_endpoint, source_endpoint, source_text, endpoint_is_unique,
    verify_execution,
)
from moveSelectionBench.historical_study.attribution import resolve_endpoint, attribute_event


class HistoricalStudyTests(unittest.TestCase):
    def setUp(self):
        self.tree = ET.ElementTree(ET.fromstring('''
<unit xmlns="http://www.srcML.org/srcML/src" xmlns:diff="http://www.srcML.org/srcDiff">
<unit filename="same.cpp"><diff:delete><function>void f(){<expr_stmt>use(realFmt);</expr_stmt>}</function></diff:delete>
<diff:insert><function>void f(){<expr_stmt>use(intFmt);</expr_stmt>}</function><function>void f(){<expr_stmt>use(fpFmt);</expr_stmt>}</function></diff:insert></unit></unit>'''))
        self.prefix = "/src:unit[@filename='same.cpp']"
        self.move = dict(match_kind='type2',from_xpaths=[self.prefix+'/diff:delete[1]/src:function[1]'],
                         to_xpaths=[self.prefix+'/diff:insert[1]/src:function[1]'])

    def test_wrong_normalized_partner_is_not_true_positive(self):
        target = ('same.cpp','void f(){use(fpFmt);}')
        self.assertEqual(match_event(self.tree,[self.move],('same.cpp','void f(){use(realFmt);}'),target),[])
        correct = self.move | {'to_xpaths':[self.prefix+'/diff:insert[1]/src:function[2]']}
        self.assertEqual(match_event(self.tree,[correct],('same.cpp','void f(){use(realFmt);}'),target),[0])

    def test_descendant_and_repeated_group_do_not_recover_parent(self):
        child=self.move | {'from_xpaths':[self.move['from_xpaths'][0]+'/src:expr_stmt[1]'],
                           'to_xpaths':[self.move['to_xpaths'][0]+'/src:expr_stmt[1]']}
        repeated=self.move | {'from_xpaths':self.move['from_xpaths']*2}
        for move in (child,repeated):
            self.assertEqual(match_event(self.tree,[move],('same.cpp','void f(){use(realFmt);}'),
                                         ('same.cpp','void f(){use(intFmt);}')),[])

    def test_revision_filtered_text_preserves_literal_spaces(self):
        tree=ET.ElementTree(ET.fromstring('''
<unit xmlns="http://www.srcML.org/srcML/src" xmlns:diff="http://www.srcML.org/srcDiff">
<unit filename="old.cpp|new.cpp"><diff:insert><expr_stmt>log("a b");<comment>//<diff:delete>old</diff:delete><diff:insert>new</diff:insert></comment></expr_stmt></diff:insert></unit></unit>'''))
        value=xpath_endpoint(tree,"/src:unit[@filename='old.cpp|new.cpp']/diff:insert[1]/src:expr_stmt[1]",'insert')
        self.assertEqual(value,('new.cpp','log("a b");//new'))
        self.assertNotEqual(value,('new.cpp','log("ab");//new'))

    def test_source_range_hash_and_line_endings_are_not_silently_changed(self):
        content=b'void f() {\r\n  use("a b");\r\n}\r\n'
        endpoint=dict(path='same.cpp',start_line=2,end_line=2,
                      text_sha256=hashlib.sha256(b'  use("a b");\r\n').hexdigest())
        with patch('moveSelectionBench.historical_study.study.git', return_value=content):
            self.assertEqual(source_endpoint(None,'revision',endpoint),'  use("a b");\r\n')
            with self.assertRaises(ValueError):
                source_endpoint(None,'revision',endpoint | {'start_line':1})
        self.assertEqual(source_text('void f() {\r\n  use("a b");\r\n}'),
                         'void f() {\n  use("a b");\n}')

    def test_repeated_text_requires_occurrence_resolution(self):
        with patch('moveSelectionBench.historical_study.study.git',return_value=b'use(x);\nuse(x);\n'):
            self.assertFalse(endpoint_is_unique(None,'revision',{'path':'same.cpp'},'use(x);'))

    def test_correct_text_in_wrong_file_does_not_match(self):
        self.assertEqual(match_event(self.tree,[self.move],('other.cpp','void f(){use(realFmt);}'),
                                     ('same.cpp','void f(){use(intFmt);}')),[])

    def test_artifact_tampering_and_incomplete_success_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            dest=Path(folder)
            files={name:hashlib.sha256(b'original').hexdigest()
                   for name in ('srcdiff.xml','srcmove.xml','results.json')}
            for name in files: (dest/name).write_bytes(b'original')
            case={'parent':'old','commit':'new'}
            receipt=case | {'status':'completed','provenance_sha256':'run','artifact_hashes':files}
            verify_execution(dest,receipt,'run',case)
            with self.assertRaises(ValueError): verify_execution(dest,receipt,'different',case)
            with self.assertRaises(ValueError):
                verify_execution(dest,receipt | {'artifact_hashes':{}},'run',case)
            (dest/'results.json').write_bytes(b'changed')
            with self.assertRaises(ValueError): verify_execution(dest,receipt,'run',case)

    def test_source_positions_resolve_comment_boundary_without_descendant_credit(self):
        text='int value; // member\n'
        tree=ET.ElementTree(ET.fromstring('''<unit xmlns="http://www.srcML.org/srcML/src" xmlns:diff="http://www.srcML.org/srcDiff"><unit filename="a.cpp|b.cpp"><diff:delete><decl_stmt>int value;</decl_stmt> <comment>// member</comment>
</diff:delete><diff:insert><decl_stmt>int value;</decl_stmt> <comment>// member</comment>
</diff:insert></unit></unit>'''))
        path="/src:unit[@filename='a.cpp|b.cpp']/diff:delete[1]/src:decl_stmt[1]"
        diag={'candidates':[{'candidate_id':1,'side':'delete','filename':'a.cpp|b.cpp','xpath':path}]}
        endpoint={'path':'a.cpp','start_line':1,'end_line':1,'text_sha256':hashlib.sha256(text.encode()).hexdigest()}
        resolved=resolve_endpoint(endpoint,text,tree,diag,'delete')
        self.assertTrue(resolved['whole_exposed'])
        self.assertEqual(resolved['candidate_ids'],[1])
        parent_text='void f(){int value;}\n'
        parent=endpoint | {'text_sha256':hashlib.sha256(parent_text.encode()).hexdigest()}
        unresolved=resolve_endpoint(parent,parent_text,tree,diag,'delete')
        self.assertFalse(unresolved['candidate_ids'])


if __name__ == '__main__': unittest.main()
