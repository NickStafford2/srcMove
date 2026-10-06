# Unknown file cannot use container displacement.

Read `before.cpp` and `after.cpp` for the code example.
The exact reviewed diff encoding in `input.srcdiff.xml` is the detector input;
source views alone do not specify which nodes srcDiff exposed as replacements.
The expectations remain explicit in `tests/behavior/test_repeated_group_location.py`.

Reviewed rationale retained from the original test:

A present srcML filename keeps this a source unit; old|new with both sides empty deliberately supplies no revision-specific path evidence.
