# Equal neighboring context does not hide cross function transfer.

Read `before.cpp` and `after.cpp` for the code example.
The exact reviewed diff encoding in `input.srcdiff.xml` is the detector input;
source views alone do not specify which nodes srcDiff exposed as replacements.
The expectations remain explicit in `tests/behavior/test_correspondence_recall_review.py`.

Reviewed rationale retained from the original test:

Identical surrounding calls in two mapped functions do not mean that the transferred statement stayed in place.
