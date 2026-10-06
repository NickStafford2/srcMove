# Unique neighbors resolve reordered repeated pairs.

Read `before.cpp` and `after.cpp` for the code example.
The exact reviewed diff encoding in `input.srcdiff.xml` is the detector input;
source views alone do not specify which nodes srcDiff exposed as replacements.
The expectations remain explicit in `tests/behavior/test_exact_neighbor_correspondence.py`.

Reviewed rationale retained from the original test:

The first repeated origin follows its unique_a context to the later destination; source/destination ordinal order alone would be wrong.
