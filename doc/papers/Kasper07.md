# intro 
Problem
- No one agrees what a clone even is.
- Don't want false positives
- Inherently subjective
DRASIS seminar. 8 expert clone code researchers used in study.

# Purpose
- Measure the degree of agreement among experts about if code is a clone or not.

# Independent Classification Results
only 50% had a classification that was agreed upon by more than 80% of the experts 

# Reasons
why two segments of code may not be a clone:
– the code is idiomatic
– the design forced repeated solutions
– the expert would not have explicitly copied and pasted the code
– the candidate was too short
– types were changed
– there was no way to refactor the code
– semantics of procedures (represents different operator)
– main portion of the code is literals
– the code was BORING!!!

Why two segments of code may be considered a clone:
– the code is idiomatic
– the code segments were very similar
– lots of changes but identifiers are very similar
– the expert would have copied and pasted the code
– the code is generatable
– context of the code segment made it a clone
– the structure was the same
