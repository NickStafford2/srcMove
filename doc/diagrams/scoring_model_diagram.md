# Proposed scoring and selection diagram

Status: conceptual. The current implementation has no probability model. See
the canonical [move-detection redesign](../plans/move_detection_redesign.md)
for semantics, performance constraints, milestones, and open decisions.

```text
srcDiff ownership and complete-construct gates
                    |
                    v
        sparse candidate-pair retrieval
   exact hash | Type-2 hash | Type-3 shortlist
                    |
                    v
             pair confidence
  similarity + structure + uniqueness + weak context
                    |
                    v
             selection utility
 confidence * matched evidence - edits - ambiguity
                    |
                    v
       non-overlapping hierarchical selection
      parent edge versus compatible child edges
                    |
                    v
         annotations + explainable JSON evidence
```

Keep two values distinct:

- **confidence** ranks how credible one deletion/insertion correspondence is;
- **utility** ranks how well selecting that edge explains the changed material.

Type-1, Type-2, and Type-3 are correlated evidence classes, not independent
bonuses to add. Location is a weak prior or tie-breaker because valid moves may
be nearby, distant, or cross-file. Revision impurity is an eligibility failure,
not a small penalty.

Do not label an uncalibrated score `P(move)`. Probability language requires a
declared labeled population, held-out validation, and calibration. BigMoveBench
can support synthetic benchmark-domain calibration but cannot by itself assign
historical-move probabilities.
