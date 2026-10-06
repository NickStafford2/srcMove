# Fragmented identifier does not corroborate unrelated full names.

Read `before.cpp` and `after.cpp` for the code example.
The exact reviewed diff encoding in `input.srcdiff.xml` is the detector input;
source views alone do not specify which nodes srcDiff exposed as replacements.
The expectations remain explicit in `tests/behavior/test_continuing_identity.py`.

Reviewed rationale retained from the original test:

Actual continuing identifiers are Aold_count and Anew_count, not the standalone names used by the two declarations under consideration.
