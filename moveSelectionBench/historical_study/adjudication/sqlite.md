# SQLite post-output adjudication

[sqlite.json](sqlite.json) accounts for all selected Type-1/Type-2 outputs and all
11 frozen positive targets. This is a single AI post-output source adjudication,
separate from the sealed source-first labels.

| Cohort | Finding |
| --- | --- |
| Ordinary 30 revisions | One Type-2 output, an incorrect correspondence: `nTab` (table-name length) paired with `bNew` (new-table iterator flag). No Type-1 outputs. Six revisions have no analyzable source change under the declared scope. |
| Six targeted revisions | Seven selected Type-1 groups, all source-supported: four functions, one declaration, one statement sequence, and one entire file. |
| Frozen target endpoints | Five of eleven selected exactly: four of six whole functions and one of five independent descendant targets. |
| Larger correct selections | Four further targets covered: two statements by a selected sequence and two functions by the selected whole file. This is coverage, not strict individual endpoint detection. |
| Uncovered targets | Two reordered `Parse` fields; srcDiff does not expose the required whole declaration endpoints. |

The two uncovered fields are `nProgressSteps` and `nQueryLoop` in target 04.
The XML reconstructs the source but represents these portions as unstructured
preprocessor/mixed text rather than the required complete insert/delete pair.
For `nQueryLoop`, the old exclusive text also has no candidate. The first limiting
stage is upstream whole-endpoint exposure, not a demonstrated selection rejection.

The Type-2 false correspondence is supported by declaration comments and uses:
old `nTab` is assigned `strlen(zTab)` / `sqlite3Strlen30(zTab)` and supplies a string
comparison length. New `bNew` is populated by `sessionChangesetNext`, tested as a
boolean and reset to zero. Equal normalized declaration syntax does not preserve
that identity.

For target 06, diagnostics mark one `sqlite3GetCollSeq` correspondence `not_move`,
but actual `results.json` selects the correct complete function. Actual selected
output and source endpoints determine the result; diagnostic labels cannot erase
an emitted move.

Three Type-3 outputs remain visible as separate observations. They do not supply
Type-2 positives. These small, purposive results support no repository-wide or
population accuracy claim, and the sample still has no confirmed Type-2 recall
denominator.
