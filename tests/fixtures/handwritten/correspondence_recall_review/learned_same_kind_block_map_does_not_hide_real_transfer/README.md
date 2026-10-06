# Learned same kind block map does not hide real transfer.

Read `before.cpp` and `after.cpp` for the code example.
The exact reviewed diff encoding in `input.srcdiff.xml` is the detector input;
source views alone do not specify which nodes srcDiff exposed as replacements.
The expectations remain explicit in `tests/behavior/test_correspondence_recall_review.py`.

Reviewed rationale retained from the original test:

Both block shells continue, so no wholly changed enclosing construct can mask a lost child report. The transfer crosses the common flush.
