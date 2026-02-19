Scoring model diagram (how decisions are made)
Purpose: make “probability of move” credible, not hand-wavy.

Use a simple box called “features” feeding into “probability model” feeding into “threshold”.

Features (grouped)

* similarity:
  * exact hash match (Type-1)
  * normalized hash match (Type-2)
  * optional: fallback similarity 
* locality:
  * tree distance
  * line/column distance
  * file/directory distance
* magnitude:
  * node count / token count / span
* behavioral heuristics:
  * include alphabetization signature
  * extract-method signature (copy to new function + call site evidence)

Probability model

* start simple: weighted score mapped to probability
* output: P(move)

Decision

* threshold T configurable
* auto-accept zone vs review zone (if I plan developer-in-loop later)

