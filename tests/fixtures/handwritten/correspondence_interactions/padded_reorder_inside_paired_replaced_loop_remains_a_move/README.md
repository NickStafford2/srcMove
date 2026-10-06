# Padded reorder inside paired replaced loop remains a move.

Read `before.cpp` and `after.cpp` for the code example.
The exact reviewed diff encoding in `input.srcdiff.xml` is the detector input;
source views alone do not specify which nodes srcDiff exposed as replacements.
The expectations remain explicit in `tests/behavior/test_correspondence_interactions.py`.

Reviewed rationale retained from the original test:

Only R crosses A and B. Padding prevents immediate-neighbor seeds from conflating identity with unchanged sibling order.
