import unittest

from tests.support.annotations import validate_annotations

PREFIX = '<unit xmlns:diff="http://www.srcML.org/srcDiff" xmlns:mv="http://www.srcML.org/srcMove">'
ORIGIN = '<diff:delete><expr_stmt mv:id="m" mv:to="/new">old();</expr_stmt></diff:delete>'
DESTINATION = '<diff:insert><expr_stmt mv:id="m" mv:from="/old">new();</expr_stmt></diff:insert>'
MOVE = {"move_id": "m", "from_xpaths": ["/old"], "to_xpaths": ["/new"],
        "from_raw_texts": ["old();"], "to_raw_texts": ["new();"]}


class AnnotationValidationTests(unittest.TestCase):
    def test_complete_pair_passes(self):
        validate_annotations(PREFIX + ORIGIN + DESTINATION + '</unit>', [MOVE])

    def test_missing_occurrence_fails_even_when_id_set_matches(self):
        with self.assertRaisesRegex(AssertionError, "endpoint mismatch"):
            validate_annotations(PREFIX + ORIGIN + '</unit>', [MOVE])

    def test_duplicate_occurrence_fails(self):
        with self.assertRaisesRegex(AssertionError, "endpoint mismatch"):
            validate_annotations(PREFIX + ORIGIN * 2 + DESTINATION + '</unit>', [MOVE])

    def test_wrong_partner_or_text_fails(self):
        for changed in (ORIGIN.replace('/new', '/wrong'), ORIGIN.replace('old();', 'wrong();')):
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                validate_annotations(PREFIX + changed + DESTINATION + '</unit>', [MOVE])

    def test_link_side_cannot_contradict_revision(self):
        with self.assertRaisesRegex(AssertionError, "revision ownership"):
            validate_annotations(PREFIX + ORIGIN.replace('mv:to', 'mv:from') + DESTINATION + '</unit>', [MOVE])

    def test_nested_opposite_revision_is_projected_out(self):
        origin = ORIGIN.replace('old();', 'old<diff:insert>unrelated</diff:insert>();')
        validate_annotations(PREFIX + origin + DESTINATION + '</unit>', [MOVE])

    def test_common_child_cannot_supply_an_exclusive_destination_annotation(self):
        destination = ('<diff:delete><diff:common><expr_stmt mv:id="m" '
                       'mv:from="/old">new();</expr_stmt></diff:common></diff:delete>')
        with self.assertRaisesRegex(AssertionError, "revision ownership"):
            validate_annotations(PREFIX + ORIGIN + destination + '</unit>', [MOVE])
