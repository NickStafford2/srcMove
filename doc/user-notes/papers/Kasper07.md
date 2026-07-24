@InProceedings{kapser_et_al:DagSemProc.06301.12,
  author =	{Kapser, Cory and Anderson, Paul and Godfrey, Michael and Koschke, Rainer and Rieger, Matthias and van Rysselberghe, Filip and Wei{\ss}gerber, Peter},
  title =	{{Subjectivity in Clone Judgment:  Can We Ever Agree?}},
  booktitle =	{Duplication, Redundancy, and Similarity in Software},
  pages =	{1--5},
  series =	{Dagstuhl Seminar Proceedings (DagSemProc)},
  ISSN =	{1862-4405},
  year =	{2007},
  volume =	{6301},
  editor =	{Rainer Koschke and Ettore Merlo and Andrew Walenstein},
  publisher =	{Schloss Dagstuhl -- Leibniz-Zentrum f{\"u}r Informatik},
  address =	{Dagstuhl, Germany},
  URL =		{https://drops.dagstuhl.de/entities/document/10.4230/DagSemProc.06301.12},
  URN =		{urn:nbn:de:0030-drops-9701},
  doi =		{10.4230/DagSemProc.06301.12},
  annote =	{Keywords: Code clone, study, inter-rater agreement, ill-defined problem}
}


# Things I will likely cite 
Suggestion of multi-point scale > binary choice.
Subjectivity is fundimental.
Reasons code is/ is not a clone

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

# Conclusions
Emphasizes the use of multi-point scale instead of binary option.
Should use clone pairs vs clone groups.
