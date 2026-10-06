# Partial resolution does not infer partner by elimination.

Read `before.cpp` and `after.cpp` for the code example.
The exact reviewed diff encoding in `input.srcdiff.xml` is the detector input;
source views alone do not specify which nodes srcDiff exposed as replacements.
The expectations remain explicit in `tests/behavior/test_exact_neighbor_correspondence.py`.

Reviewed rationale retained from the original test:

Only the repeat immediately before the original unique statement has independent evidence. The first occurrence remains an equivalence.
