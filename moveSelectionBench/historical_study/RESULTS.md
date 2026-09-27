# Type-1 and Type-2 historical results

Completed 2026-09-27. This study establishes real successes and concrete misses;
it does **not** establish universal or representative historical accuracy.
No production detector behavior, Type-3 policy, Phase 5, or VERSION changed.

## Execution and evidence

The study ran 90 consecutive first-parent comparisons (30 per repository) and
16 source-selected comparisons: six SQLite, six Notepad++, and four OpenCV.
Of these 106 comparisons, 83 had analyzable C/C++ changes and completed both
tools; 23 had no admitted source change. There were no execution failures.
Ordinary, results-only, and diagnostic ordinary results agreed on all 83 inputs.

Primary source labels were frozen before execution and corroborated by a second
AI agent. Eight disputed labels remain excluded from the confirmed-target
denominator. This is AI review, not independent human annotation. Every selected
Type-1/Type-2 output has an artifact-bound post-output adjudication, including
unresolved findings. Source reviews, second reviews and their seal are retained
unchanged; post-output corrections are separate.

The production srcMove executable SHA-256 is
`359baf50869312f88f8737becfb76fc47915cc9ad63c1b5a49fe3a81de03ebaa`.
Full tool/source/configuration identities, execution receipts and adjudication
hashes are in [`results.json`](results.json). The
[protocol and commands](README.md) explain reproduction.

## Detection of confirmed source targets

These are exact endpoint detections with the expected match type. A larger
selection or a selected descendant does not count as exact target detection.

| Cohort and target | Confirmed targets | Exact detection | Covered by larger selection | Descendants only | No coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Targeted Type-1 whole constructs | 18 | 11 | 2 | 5 | 0 |
| Targeted Type-1 independent smaller moves | 8 | 4 | 2 | 0 | 2 |
| Ordinary Type-1 independent smaller moves | 3 | 3 | 0 | 0 | 0 |
| Targeted Type-2 independent smaller move | 1 | 0 | 0 | 0 | 1 |

The three ordinary positives are from the previously studied Notepad++ Scintilla
revision; they are not fresh held-out evidence. Whole constructs include
functions, structs/classes, and standalone typedefs, not just functions.
No whole-construct Type-2 positive was confirmed in this fresh targeted search.
Do not pool these rows into one general recall score or treat all output groups
as additional frozen targets. Ordinary source inventories are not complete
enough to claim exhaustive window recall.

The source-selected search inspected 49 additional diffs (nine SQLite, twenty
Notepad++, twenty OpenCV). It stopped at the declared limits, retaining the
Type-2 shortfall rather than turning broader structural edits into Type-2.

## What is missing and why

1. **Five Type-1 whole typedef targets lose their wrapper.** OpenCV reports
   smaller `function_decl` children without the substantive `typedef` keyword.
   Both complete source endpoints are exposed in XML, but the reviewed complete
   typedefs are absent from the candidate inventory. This is a candidate-policy
   limitation, not recovery of the whole target and not an upstream absence.
2. **Two Type-1 field reorders have no complete exposed endpoints.** SQLite
   `80c438613a68` moves `nProgressSteps` and `nQueryLoop`. The source review
   confirms movement, but srcDiff's preprocessor/mixed representation does not
   expose complete declaration pairs. These are end-to-end misses; exclude them
   only from an explicitly conditional srcMove denominator, not from the ledger.
3. **Four strict target misses are larger-selection choices.** SQLite selects
   the whole renamed version-info file instead of its two reviewed functions,
   and a two-statement sequence instead of its separately reviewed components.
   Movement is represented, but at a different granularity.
4. **One real Type-2 call reorder is ineligible.** Notepad++ `fb086bbcdaad`
   changes `getClientRect` to `getWindowRect` while moving the continuing rectangle
   query across `setPositionDpi`. Both complete expression statements become
   candidates, but `expr_stmt` is excluded from Type-2 grouping. No exact or
   enclosing output recovers the target. The lexical Type-2 label does not claim
   semantic equivalence of the changed APIs.
5. **One selected Type-2 pair has the wrong identity.** SQLite ordinary case 15
   pairs `int nTab = 0` (table-name length) with `int bNew = 0` (iterator flag).
   Normalized similarity and displacement do not establish continuing identity.

The per-event source ranges, rationale, candidate/selection evidence and actual
selected indices are in the [SQLite](adjudication/sqlite.json),
[Notepad++](adjudication/notepadpp.json), and
[OpenCV](adjudication/opencv.json) adjudications. Actual output controls detection
scoring: a unique-correspondence diagnostic alone can disagree with a selection
reached through the retained repeated-group path.

## Output correctness and unresolved precision

Across the two historical cohorts, the output inventory contains 208 Type-1 and
nine Type-2 groups. These inventory totals are not independent move-event counts:

| Output type | Reviewed valid independent selections | Reviewed valid carried fragments | Confirmed wrong pairs | Unresolved one-to-one | Unresolved repeated groups |
| --- | ---: | ---: | ---: | ---: | ---: |
| Type-1 | 66 | 91 | 0 | 27 | 24 |
| Type-2 | 0 | 1 | 1 | 7 | 0 |

Carried fragments may be correct annotations but are not independent recall
events. Preprocessor restructuring accounts for many unresolved results. The
absence of confirmed Type-1 false pairs is **not** evidence of 100% precision:
27 one-to-one results and 24 groups remain unresolved. Repeated groups are not
expanded into individual pair claims. `results.json` reports precision counts
and uncertainty bounds separately by cohort, type, output unit, and scope;
do not promote an adjudicated-only rate to overall precision.

## Retained Type-2 and controlled evidence

A separate audit independently checked the source identities of the eight
previously claimed whole-function Type-2 positives, then replayed the retained
source-verified XML with the same current binary. **All eight were detected at
the correct complete endpoints as Type-2:** three SQLite functions and five
Notepad++ methods. Both inputs preserve execution-mode equivalence. These are
previously exposed development cases, not new held-out recall. The other 140
selected outputs across those two inputs remain outside this target audit;
it supplies no full-output precision estimate.

The twelve source-defined Type-1 controls also pass: six positives detected
(two whole functions, four independent smaller moves), and six negative cases
emit no moves. These establish controlled behaviors only. They contain no
Type-2 positive census and do not establish historical accuracy.

[`supplemental_results.json`](supplemental_results.json) retains compact results
and raw report hashes for these separate evidence sets. The old SQLite shell
`zRealFmt → zIFmt` mismatch remains a known separate finding in the
[earlier audit](../type12_evaluation.md#sqlite-endpoint-correction); it has not
been repaired or relabeled by this study.

## Source-review corrections and practical limits

The frozen OpenCV ordinary-05 inventory incorrectly treated a rename/extraction
as addition-only because a name-only Git listing omitted the old `lapack.cpp`
path. Post-output source review corrected the interpretation and reviewed the
emitted results, but cannot retroactively make this a complete blind recall
inventory. The SQLite version-info target inventory also lists only the new
path, although both old and new target sources were actually reviewed. Both
discrepancies are preserved in [`source_inventory_audit.json`](source_inventory_audit.json).

Future sampling must use the production `inventory_changed_paths` behavior
(`git diff --raw --no-renames`) and review both old and new paths before labeling.
Do not revise these sealed source files or treat discovered output events as
prespecified recall positives. Large OpenCV merges and the SIMD change/revert/
reintroduction cases are correlated; these results do not establish population
coverage across repositories or languages.

## Next evidence-driven work

Prioritize complete Type-1 typedef candidates and minimal source regressions for
the two preprocessor field misses. Preserve whole-target/descendant distinctions.
For Type-2, investigate the expression-statement eligibility boundary alongside
the demonstrated wrong-identity case; widening eligibility alone is not validated
as an improvement. Keep the current run immutable and compare any future repair
as a separate executable/run. Those cases would then be development evidence;
fresh source-reviewed cases are needed for a later held-out claim. Type-3
adoption and Phase 5 remain deferred.

Verification: Docker `make test` passed all 13 steps; after the evaluation XPath
resolver optimization, the focused suite passed 30 unit tests and 21 semantic
contracts. No expected detector output was weakened to make this study pass.
The [verification record](verification.json) retains commands and derived-report hashes.
