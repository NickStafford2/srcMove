# Type-1 and Type-2 defense evidence

Status: evidence audit and proposed bounded evaluation, 2026-09-27. No new
detector experiment has been run for this proposal. Audited checkout:
`8d72119af6f17446061899ed9b001cb38c6fc82d`; tracked and untracked status was clean.
Type-3 production behavior stays unchanged; further adoption and Phase 5 are
deferred. This protocol does not require an algorithm or VERSION change.

The [architecture](../doc/architecture.md) defines current behavior. The
[suite history](README.md) owns earlier experiment details; the
[benchmark reporting rules](../benchmarking/README.md) and
[BigMoveBench methodology](../bigMoveBench/docs/methodology.md) define their
respective interpretation boundaries.

## What the existing evidence supports

This audit inspected Git history, source-review records, retained JSON/XML,
the Type-2 adoption comparison, and the SQLite source diff. It is not an
exhaustive re-adjudication of every historical output or a rerun of old binaries.

| Evidence | Supported claim | Missing evidence |
| --- | --- | --- |
| Type-1 contracts and normalized fixture inventory | Specific location, hierarchy, and conservative-fallback behavior is tested. | Fixtures used in development are not an independent historical precision/recall sample. |
| Notepad++ `e59774add26b0130d38aaf722aceb0259ccc0078`, `Document.h` | The retained Type-1 adoption comparison suppresses 12 previously selected groups under missing context. | Those 12 were not independently established false moves; zero output does not establish improved precision. |
| Initial Notepad++ handler-transfer and rename comparisons | Reviewed handler bodies have representatives; finer in-place edits expose no unique Type-2 pairs. | Body representatives do not establish whole-handler detection; fragment granularity is not the default. |
| Default-granularity SQLite extension and Notepad++ localization transfers | Prior review identifies three and five whole Type-2 function targets, respectively, reported selected. | No exhaustive review of all other selected outputs or all missed source events; easy file transfers dominate. |
| Notepad++ `682a8edafa2048e0cf7d88060fda772e2ed0f30b` declarations | Source-only second review supports two stationary declarations left unselected. | Selection was retrospective; diagnostics are ambiguous, not proven stationary; the access-changing declaration stays unresolved. |
| OpenCV `9ba4bb7355` edited declarations | Of three prespecified targets, `_dpdk` is selected; `_dpdr` and `_dpdt` remain unresolved normalized groups. | Five selected pairs include four post-output corroborations; they cannot become five prespecified positives. |
| SQLite shell reorder | The source contains a real edited reorder, but the selected endpoint identity is wrong; see below. | The earlier claim of recovered whole-target recall is unsupported. |
| Type-2 adoption at `4b1d0f2` | Retained comparison has 172 inputs, 14 history inputs, nine changed XML fixtures, and zero historical JSON/XML changes. | Compatibility is not independent accuracy. No current-HEAD accuracy score follows from this older comparison. |
| BigMoveBench positives and known-false-positive pairs | Strict whole-fragment synthetic detection/classification and whole-pair rejection. | Neither general historical recall nor precision; incidental descendants are not adjudicated by whole-pair labels. |

The adoption totals above were recounted from
`build/type2-adoption/comparison.json`, not inferred from commit titles.
Historical samples, reductions, later replays, and repeated outputs from the same
revision must not be added together as independent observations. The retained
upstream Notepad++ parser crash remains a failure record, not a detector miss.

## SQLite endpoint correction

For SQLite parent `753df3d91adc227b9ae503458212efea12c44af7` to commit
`c799c15dbef70dd8ee63be2c4b77ebeacce1df00`, source review identifies the
`dotCmdMode` floating-point block as `zRealFmt/--realfmt` becoming
`zFpFmt/--fpfmt`, crossing the unchanged line-limit and quote blocks.
The integer block continues as `zIntFmt/--intfmt` to `zIFmt/--ifmt`.
The local Git source diff confirms these distinct roles.

However, the retained baseline **and adoption trial** select the whole
`zRealFmt` block paired with the **`zIFmt` block**. In retained srcDiff XML,
the `zFpFmt` block is aligned with the old `zIntFmt` block as mixed common/edit
structure, rather than exposed as the required whole insertion. The diagnostics
list the selected parent as candidates 7→3, with the child 5→1 unselected.
Changing their location decision to `relocated` did not repair identity.

Under the existing source-reviewed oracle this is an incorrect correspondence
and a missed intended whole target, not a true positive. The missing whole
insertion is an upstream exposure limitation; it must be reported separately
from conditional srcMove recall. It does not excuse the emitted wrong partner.
The reduced synthetic reorder can still test anchor behavior, but cannot
substitute for the full source identity check. These are retained-run findings;
current HEAD needs a separately identified replay before making a current claim.

Audited local artifacts (ignored, preserve unchanged):

| Relative to srcMove | SHA-256 |
| --- | --- |
| `benchmark-results/correspondence-type2-gate-trial/sqlite-shell/source-review.json` | `a67999e44a6ca47fa3f984252293ebc38c60e8c78725bc375e55eb61630d4c49` |
| `benchmark-results/correspondence-type2-gate-trial/sqlite-shell/srcdiff.xml` | `c6b29bbb5803069e2c612a6cec9209308b06061020150669401ccd9d7eb2590c` |
| `benchmark-results/correspondence-type2-gate-trial/sqlite-shell/baseline.json` | `439209fcabca0c2dab39bd1c196994fe5a67c3165a6ad5742cdaffe418a59108` |
| `build/type2-adoption/comparison/history/sqlite-shell/trial.json` | `9568c2314ac992e0a143788694f37fbd0bf157cb34a66efbca0859a414d6678d` |
| `build/type2-adoption/comparison.json` | `292c850ccb04853c5fe42b615d5a1d406ae13164113081653ebf2cc877fcc6d5` |

The separate source-only review is
`benchmark-results/correspondence-type2-gate-trial/opencv-sqlite/sqlite-fpfmt-independent-review.json`.
The older `sqlite-shell/reviewed-conclusions.json` and
`build/common-anchor-baseline/reviewed-conclusions.json` contain the superseded
interpretation. Preserve them as historical records, not final defense claims.

## Bounded evaluation proposal

Use three separate evidence sets. Proposed caps are workload limits, not accuracy
targets. Freeze selection, scope, labels, and scoring before new detector runs.

1. **Retained diagnostic set:** replay the existing 14 adoption history inputs
   and the four OpenCV/SQLite same-file probes. Deduplicate by repository,
   parent/commit, and file scope (at most 18 inputs); freeze exact full revisions
   from their manifests. Resolve both endpoints of every previously claimed
   positive, starting with SQLite. These remain development evidence.
2. **Fresh historical set:** at most 12 previously unevaluated adjacent revision
   pairs, four each from SQLite, OpenCV, and Notepad++. Inspect at most 60
   candidate diffs and spend at most two working days on source labeling.
   Record fixed repository tips, traversal, search terms, all inspected IDs,
   inclusion/exclusion reasons, and final full hashes. Seek six move-bearing
   pairs (both types, including same-file order, container, and file changes)
   and six in-place/restructuring or unrelated-edit controls. Freeze complete
   file subsets with both endpoints, at most four files and 800 changed lines
   per pair. Review surrounding source, not only diff hunks. If quotas are
   unavailable, report the smaller set and missing strata; do not search until
   detector results look favorable. This is a purposive case study, not a
   representative repository sample. Historical language scope is C/C++.
3. **Controlled set:** 24 source pairs, six positive and six negative scenarios
   instantiated in both exact Type-1 and normalized Type-2 forms. Reuse fixture
   conventions, logical filenames, and existing runners. Freeze source-defined
   endpoints and negatives before generating srcDiff. Existing XML contracts
   supplement this set but are not additional independent trials.

| Controlled positives (each Type-1 and Type-2) | Controlled negatives (corresponding exact/normalized content) |
| --- | --- |
| Whole function across stable files | Line shift or local edit in a continuing construct |
| Whole construct across mapped containers | Wrapper added or removed without independent relocation |
| Same-file reorder across a declaration | Repeated alternatives with no defensible unique identity |
| Same-file reorder across a conditional | Missing-context continuing construct, known stationary from source |
| Independent child movement inside an edited parent | Unrelated same-shape replacement with different continuing roles |
| Whole parent transfer with carried children | SQLite-shaped competing roles: one real transfer and a forbidden wrong partner |

The last negative scenario is a mixed control: require the intended transfer
and forbid the wrong pair. Other cases may also contain valid incidental moves;
specify exact forbidden pairs rather than automatically requiring zero output.
Type-2 forms must differ beyond Type-1 canonical equality while preserving
consistent name mapping and literal categories. Include comment/format changes
in Type-1 controls. Ambiguous identity is an unresolved label, never a fabricated
negative. Construction intent alone must not settle an indistinguishable pair.

## Independent labels and counting units

A source reviewer inventories **all** in-scope independent move events, including
unreported ones, before seeing detector output. Record old/new paths, full source
ranges and text hashes, construct kind, continuing role, source evidence type,
movement rationale, enclosing event ID, and uncertainty. A second source-only
reviewer checks labels and resolves disagreements before unblinding. If only one
reviewer is available, explicitly report single-reviewer evidence. Record reviewer
identity and whether prior detector outcomes were known; retained cases cannot
be made held out by relabeling them.

After freezing labels, inspect every emitted Type-1/Type-2 result in scope for
precision. Adjudicate previously unlisted outputs from source, logging additions
and disagreements separately; do not silently revise the frozen recall oracle.
Keep these units separate:

- **Whole target:** exact reviewed source and destination constructs must both
  be selected in one result. Descendants, overlap alone, or a wrong normalized
  partner cannot satisfy it. Match by revision-filtered source identity plus
  paths/ranges, not diagnostic class or candidate ID alone.
- **Independent descendant target:** explicitly labeled child relocation with
  its own identity and displacement. Score in a separate stratum. A carried
  child is coverage of the parent event, not another independent true positive.
- **Partial evidence:** descendants of a missed whole target, or a selected
  ancestor covering a child without selecting it. Report coverage separately;
  do not convert it into strict whole-target or child-pair detection.
- **Repeated groups:** review group validity separately and report unresolved
  cardinalities. Never expand `move_pair_count` into asserted endpoint matches.
  This evaluates the existing policy without starting Phase 5.

Within each declared unit and Type-1/Type-2 stratum, report TP, FP, FN and
unresolved counts. Precision is TP/(TP+FP) over adjudicated selected pairs;
recall is TP/(TP+FN) over the independently inventoried positives. Also report
how many selected results remain unresolved: precision bounds are
TP/(TP+FP+U) to (TP+U)/(TP+FP+U). Use N/A for zero denominators. Do not pool
whole targets, children, repeated groups, or synthetic and historical cases.
Report per-revision counts so correlated descendants do not suggest a large
independent sample. Do not attach population confidence claims to this purposive
design or to the artificial positive/negative balance.

Detection and type assignment are separate: score correct endpoints regardless
of returned type, then strict correct-type detection and a type confusion table.
Keep false reported Type-1/Type-2 pairs in the precision denominator even when
their true source category is unrelated or outside those types. Type-3 results
remain visible as interference/coverage observations, without changing behavior.

For each missed target, record the limiting stage: upstream failure, whole
endpoint not exposed, candidate filtering, correspondence/identity, location,
or selection. Report both end-to-end outcomes over all frozen targets and
conditional detection over independently verified exposed targets. Failures and
ineligible targets remain in the ledger; neither may disappear into exclusions
or be presented as conditional srcMove misses.

## Execution and deliverables

Freeze the current source SHA, dirty patch if any, executable hashes/build
receipts, dependency revisions, command flags, environment, source hashes,
srcDiff XML hashes, and oracle revision. Use Docker and default statement
granularity, with actual logical paths and declared `.in=C` registration.
Use the production history interfaces for new historical execution; retain
per-target scoring as an evaluation layer, not a competing history database.
Existing replay adapters are useful patterns but need Type-1/Type-2 endpoint
oracles; they must not infer ground truth from diagnostics.

Execute once after labels are sealed. Record ordinary results, diagnostics,
failures/timeouts, elapsed time and peak memory. Check normal/results-only
equivalence on each selected input. If a defect is found, preserve the run;
any later repair creates a separate evaluated revision and makes these cases
development evidence. A fresh holdout would then be required for a held-out claim.
Comparisons to older binaries are optional and must use identical frozen inputs
and full endpoint scoring, not merely changed output counts.

Deliver a checked-in source-selection/label manifest and compact adjudicated
counts, with checksummed raw evidence retained under an ignored run directory.
Package enough source provenance and reproduction instructions that professors
need not rely on mutable local clones or inaccessible ignored summaries alone.
Review licensing before redistributing upstream snapshots. Stop at the stated
caps and report coverage gaps. The defense can claim measured behavior on this
declared sample; broader accuracy and improvement claims remain unsupported
until the corresponding independent measurements exist.
