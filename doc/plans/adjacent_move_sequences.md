# Adjacent moved sequences

Status: Stage 1 and its compound reporting projection implemented October 5,
2026; consumer automated checks and live History verification passed. The two known
Type-3 edits-in-place failures are retained.
Stages 2a/2b remain proposed. The initial code inspection used srcMove
`e04186d1946088ed682680346c5f5329cfe60d8f` (clean working tree at inspection).

## Objective and recommendation

Represent adjacent statements or declarations that relocate together as an
ordered sequence, even when their enclosing block is unavailable or does not
match. Preserve the constituent correspondences and uncertainty. Do not claim
to recover the number of developer editing actions.

Implement in stages:

1. Add conservative ordered aggregation after selection, initially for unique
   one-to-one Type-1 reports. This improves reporting granularity without
   changing detection, similarity, or proposal selection.
2. Add bounded, indexed whole-sequence Type-1/Type-2c candidates before
   selection, if the reviewed examples show that aggregation is insufficient.
3. Consider bounded anchored Type-3 sequence proposals only after the first two
   stages have evidence. Do not add unrestricted subrange search or beam search.

This narrowly scoped plan extends the broader
[move-detection redesign](move_detection_redesign.md). Location eligibility
remains governed by the [correspondence plan](correspondence.md).

## Compound reporting slice: one reported Type-1 move per ordered run

Implemented October 5, 2026. The user's intended outcome is one
larger Type-1 move for an unchanged contiguous run, rather than a primary list
of its individual moves. Stage 1 supplies the conservative grouping evidence;
its additive sequence records are an intermediate representation.

The srcMove-owned reporting projection after selection replaces each
qualifying run with one compound Type-1 report in the primary reporting view,
and keeps each ungrouped selected move as one report. It retains the atomic
selected matches underneath for provenance, exact member correspondence, and expansion.
History and srcDiffVisual consume that projection, rather than inventing
their own grouping. This gives one larger reported move without changing which
matches the detector selects or introducing window search.

For example, an unchanged ordered transfer of `A; B; C;` reports one Type-1
move with one source endpoint covering the three siblings and one destination
endpoint covering their counterparts. Member links remain A→A, B→B, C→C.
It is a sequence endpoint, not an invented enclosing AST block. An unmatched
statement, meaningful intervening child, different parent, or reordered member
continues to stop aggregation under the existing conservative rules.

This uses the distinct report kind `ordered_sequence` with
`content_relationship: type1`, an ordered endpoint on each side, and member
references. The internal report kind need not appear in the primary UI label:
the viewer can say “Type 1” and highlight the complete run, with optional member
expansion. Do not flatten its members into an existing content-equivalence
group, whose endpoint sets imply possible partners across those sets.

The existing `sequence_reporting_unit_count` is the basis for the primary
report count, and expose the atomic group count separately with an explicit
label. This is a count of reported relocation units, not developer actions.
Keep whole-method benchmark coverage separate: an interior sequence does not
become a detection of its enclosing method.

### Alternatives and tradeoffs

| Option | Assessment |
| --- | --- |
| Display a sequence alongside all its members as primary moves | Preserves compatibility, but leaves the user's counting and presentation problem unresolved. Keep this only as a diagnostic view. |
| Emit one compound report, retaining atomic matches internally | Implemented slice. Uses existing evidence, provides the intended count and appearance, and avoids changing selection. Uses an explicit consumer/output contract. |
| Flatten different statements into an existing equivalence group | Reject: can imply incorrect cross-member partner links. |
| Detect whole sequence candidates before selection | Potential later recall improvement. Can recover unmatched/renamed interior code, but changes detection and requires competition, bounds, and renewed evaluation. Not necessary merely to report existing runs once. |

### Independent review decisions and consumer acceptance gates

An independent child agent reviewed the canonicalization and reporting
contract during implementation. The decisions and acceptance gates are:

1. Ordered member Type-1 equality plus reliable, barrier-free adjacency
   establishes aggregate ordered canonical equality. Exact canonicalization
   has no cross-member rename mapping and retains each complete child root.
   Review identified substantive descendants inside `diff:ws` and unknown
   diff wrappers as exceptions to the previous transparency assumptions;
   these now stop sequence grouping conservatively. No extra LCS or whole-run
   comparison is needed once these evidence barriers hold.
2. The additive schema-2 contract is `reported_moves`, `reported_move_count`,
   and `reported_content_relationships`. Legacy `moves` and its counts remain
   atomic evidence. Count one collection at a time. The canonical implemented
   contract is in [architecture](../architecture.md#ordered-move-sequences).
   Software `VERSION` is unchanged.
3. Ordered endpoints retain member XPaths and original XML partner links,
   without wrapping siblings in a synthetic AST node. The primary viewer item
   represents the run; its detailed connections remain one per member pair.
   This does not imply detection of the enclosing block or include an
   intervening unmatched statement.
4. Verify that reported units partition selected groups exactly once, that
   compound endpoints have equal ordered canonical content, and that gaps,
   repeats, barriers, and permutations retain the expected smaller reports.
   Check normal/diagnostic/results-only output and History/API/export/UI count
   agreement. Add focused consumer compatibility tests; retain detector
   preservation checks rather than changing benchmark oracles to reward grouping.

Review scope: settle reporting semantics first. Stage 2a/2b remain deferred;
this recommendation does not authorize their implementation. No new matching
search is required. Projection is linear in member references once Stage 1
has built the runs; any aggregate equality verification must also account for
the total canonical content processed and avoid all-pairs comparisons.

## Evidence and problem boundary

The author's working draft is in `thesis-workspace/thesis-draft-final/`; the
requested `thesis-final-draft/` directory does not exist in this workspace.
Relevant current prose:

- [Chapter 3, Section 3.9](../../../thesis-workspace/thesis-draft-final/03-what-is-a-source-code-move.md):
  predictions and reference judgments require comparable granularity; reported
  groups are not counts of historical editing events.
- [Chapter 4, Sections 4.3, 4.6–4.7](../../../thesis-workspace/thesis-draft-final/04-srcmove.md):
  candidates, containment conflicts, greedy selection, and existing count units.
- [Chapter 7, Sections 7.3.5 and 7.6](../../../thesis-workspace/thesis-draft-final/07-moves-in-repository-history.md):
  moved sequences sometimes appear as several smaller reports.

Verified code boundaries:

- [`region_filter.cpp`](../../src/region_filter.cpp),
  `collect_candidates_streaming`, retains pure complete constructs and rejects
  substantively mixed enclosing candidates. Preferred children can survive.
  A partial-block transfer need not have an eligible whole-block candidate.
- [`content_group_builder.cpp`](../../src/move_registry/content_group_builder.cpp),
  `build_content_groups`, constructs proposals before greedy selection.
- [`group_selection.cpp`](../../src/move_registry/group_selection.cpp) prevents
  candidate reuse and enclosing/nested selected extents. Distinct adjacent
  reports therefore demonstrate fragmentation, not by themselves overlapping
  duplicate coverage. Test literal duplicate coverage separately.
- [`move_candidate.hpp`](../../src/move_candidate.hpp) has XML spans,
  `structural_parent_key`, and a same-element-name sibling index. These do not
  establish adjacency among all meaningful siblings in a particular revision.
- [`summary.hpp`](../../src/summary.hpp) and
  [`pipeline.cpp`](../../src/pipeline.cpp) count existing reported groups,
  estimated pairs, and annotated candidate endpoints separately.

### Primary History example: five consecutive declarations

OpenCV History comparison 5 in the retained October 5 snapshot provides a
cleaner motivating case than the supplied screenshot. `JacobiSVDImpl_`
transfers from `modules/core/src/lapack.cpp` to
`modules/core/src/lapack.simd.hpp`. The start of its body contains:

```cpp
VBLAS<_Tp> vblas;
AutoBuffer<double> Wbuf(n);
double* W = Wbuf.data();
int i, j, k, iter, max_iter = std::max(m, 30);
_Tp c, s;
```

The saved results report these as five unique one-to-one Type-1 groups.
Inspection of the saved srcDiff XML confirms they are consecutive direct
children of one `block_content` on each side, in the same order, with only
whitespace elements between them. There is no whole-`JacobiSVDImpl_` report.
This run is a concrete positive oracle for Stage 1: one ordered aggregate
retaining five links. It is not an experimental result for the proposed code.

The following `double sd;` declaration has no selected report and must stop
Stage 1 from extending through it. Later exact statements cannot be joined by
pretending that the omitted declaration does not exist. Other parts of the
function differ, but the reason it was not selected as a whole has not been
diagnosed; do not attribute that outcome to the Type-3 threshold without
candidate and proposal evidence.

Snapshot, commit, group, XPath, and checksum locators are recorded in the
[source ledger](../../../thesis-workspace/references/source-ledger.md#opencv-adjacent-declaration-sequence-inspected-2026-10-05).
This is an AI inspection of retained output/source representation, not human
validation or an estimate of how frequently sequences are fragmented.

### Secondary counterexample: the screenshot is reordered

The supplied screenshot shows:

```text
original: IdleWork, QueueIdleWork, SetIdle
modified: SetIdle, IdleWork, QueueIdleWork
```

Strict ordered aggregation would join `IdleWork + QueueIdleWork` and leave
`SetIdle` separate, assuming both reports satisfy the metadata rules below.
It cannot honestly describe all three as one unchanged Type-1 sequence.
A reordered bundle could be a separate representation later; it must retain
the permutation and assess its aggregate content relationship independently.
Do not relax Type-3 similarity merely to make this example one report.

The commit pair exists as `notepadpp-ordinary-13` in the frozen
[source review](../../moveSelectionBench/historical_study/reviews/notepadpp.json)
(`bf9f8b4c9549dadd23f483190dd1e1e4707da3ea` →
`e59774add26b0130d38aaf722aceb0259ccc0078`). The
[adjudication](../../moveSelectionBench/historical_study/adjudication/notepadpp.json)
contains declaration endpoints. Retained XML is at
`benchmark-results/historical-type12-20260927/notepadpp/notepadpp-ordinary-13/srcdiff.xml`
when the local benchmark outputs are available. That older study is distinct
from the screenshot's srcMove SHA `4716608701` and artifact `f23e2a1fc6`;
the screenshot artifact was not located in tracked files during this review.
Use a source-pair fixture for the precise permutation, and replay the actual
artifact separately when available. Do not reuse its displayed count as a
measurement for the current checkout.

## Stage 1: ordered aggregation of selected correspondences

### Revision-specific adjacency

Extend the streaming collector with compact structural metadata:

- immediate non-diff structural parent identity within the revision and file;
- child ordinal among all meaningful direct children, across element kinds;
- revision ownership, complete-child boundaries, and unknown/barrier flags.

Diff wrappers are transparent for structural parent identity. Common code
belongs to both inventories; deleted and inserted code belong to their
respective inventories according to the existing nested-membership rule.
Count children that fail candidate eligibility too: a filtered `return;`,
`break;`, or short call must still prevent a false adjacency claim. Treat
preprocessor structure and unknown membership as barriers initially. Ignore
formatting/comments consistently with the declared Type-1 policy, while
retaining them for source display. A complete nested conditional is one child
of its outer parent; its inner statements belong to another sibling list.

Do not infer adjacency from line numbers, candidate IDs, same-kind XPath
indices, or XML event distance. Parent identities need only be stable within
each revision for this stage; they do not establish cross-revision parent
correspondence or relocation.

### Linking rule

Start with selected unique one-to-one Type-1 structural-child reports that
already passed relocation policy. Each link has exactly one source and one
destination. Partition by source file/parent and destination file/parent.

Link report `p` to report `q` precisely when:

```text
q.source.ordinal      == p.source.ordinal + 1
q.destination.ordinal == p.destination.ordinal + 1
```

Both endpoints must be complete, non-overlapping direct children with reliable
metadata and no intervening meaningful code. Emit maximal paths of length at
least two; retain singletons as existing reports. This is a deterministic chain
problem, not connected-component clustering by proximity. Ambiguous NxM,
one-to-many, wrapper-only, missing-context, and Type-3 reports remain separate
in the first version. No new location inference occurs here.

Example: `A B C` moving unchanged produces one ordered aggregate.
`A B C` becoming `C A B` produces `A B` plus `C`.
`A B` becoming `A X B` does not aggregate, even if `X` was filtered out of
the candidate registry.

### Output contract

Implemented Stage 1 uses a separate sequence record:

```text
sequence_id
member_move_ids: [p, q, ...]       # explicit selected 1:1 links, in order
from: {revision_file, parent_id, first_child_ordinal, last_child_ordinal, member_xpaths}
to:   {revision_file, parent_id, first_child_ordinal, last_child_ordinal, member_xpaths}
content_relationship: type1
policy: ordered_adjacent_v1
```

Retain existing `moves`, XML move IDs/partner links, and existing count meanings.
Add `sequence_cluster_count` for aggregates of at least two member reports and
`sequence_reporting_unit_count` defined as existing group count minus the
number of aggregated member groups plus aggregate count. Repeated ambiguous
groups count as one residual reporting unit, not as resolved sequences.
Keep member count and source coverage available. Neither new count estimates
developer actions. Settle schema/consumer compatibility before coding output;
do not infer a software release or edit `VERSION` as part of this work.

Do not put heterogeneous members into the existing content equivalence groups:
their endpoint sets represent possible partners, and annotation writes partner
XPath unions. Combining unrelated `A` and `B` there would imply false A→B links.
srcDiffVisual can later collapse a sequence and expand its retained links.
That consumer work is a separate task in its owning repository.

### Cost

Let `N` be input XML events and `M` selected eligible links. Child metadata adds
O(N) counter updates, plus O(B) conservative barrier propagation, where `B`
counts visits to active source frames/children when malformed whitespace or
unknown wrappers invalidate their contexts. `B` depends on active nesting;
do not claim strict linear traversal for arbitrary malformed nested XML.
Retained context uses O(N) record slots in the conservative bound, plus the
actual stored parent-ID strings.
Sort/index links in O(M log M) time and O(M) extra space; scan chains in O(M).
Hash lookup is expected constant time, not a worst-case guarantee. Do not scan
all pairs. These are incremental bounds, not claims that existing detection
and selection have linear complexity.

## Stage 2: detecting changed sequences

Aggregation cannot recover an unmatched edited statement or make several
interior statements equal a complete method. Use sequence endpoints as new
proposal units before selection if those capabilities are needed.

### 2a: bounded exact and consistent-renaming windows

Generate deterministic contiguous windows of complete pure revision-exclusive
children, with at least two members, within one structural parent. Enumerate
lengths up to a configured statement cap `K` and lexical-unit cap `T`.
Cross transparent diff wrappers; stop at common children, directives, unknown
membership, or impure member boundaries. Do not admit an entire mixed block.
Window lengths, caps, and truncations must be recorded. Choose numerical caps
from frozen workload inventories before comparative evaluation; they are not
established tuning values in this plan.

Build exact identities with explicit member boundaries/kinds. Build Type-2c
representations with one identifier mapping over the entire ordered window.
Use indexed identities and full equality verification after hashing. Repeated
window classes remain unresolved; do not zip occurrences by order.

**Do not concatenate candidate-local normalized vectors.** For example,
`use(x); save(x);` → `use(a); save(b);` can look consistent separately but is
inconsistent as a sequence. Conversely, `x,y` → `a,a` violates injectivity.
The existing forms builder must consume a whole-window lexical/name stream or
equivalent retained pre-normalization evidence. Raw text concatenation alone
does not preserve srcML structure. Account for this retention/replay cost.

Require positive aggregate relocation evidence for all sequence match types.
Cross-file paths can establish the existing path-based evidence; same-file
sequences require mapped container/anchor/ancestry context. Adjacency only
defines endpoint boundaries. Do not inherit the current Type-3 relocation
exception. Keep that existing defect's fix separate and regression-visible.

Submit a sequence as one atomic proposal with ordered member references and
complete covered extents. It competes with enclosing constructs and members
under existing one-use/containment constraints. Score unique covered units once,
apply current content weighting to the aggregate, and retain child fallback.
Do not add an arbitrary bonus just to reduce report counts. Verify the behavior
on parent/sequence/child competition before adopting selection changes.

For `S` eligible direct children, there are O(SK) windows. With each window
bounded by `T`, straightforward representation construction costs O(SKT)
time/space before reductions; do not claim O(S) with copied representations.
Hash indexing avoids unrestricted deleted-window × inserted-window comparison.
Set a global generation/memory cap too, and report incomplete search explicitly.

### 2b: optional anchored Type-3 windows

Begin only with at least two unique verified exact links in monotone order
within the same source-parent/destination-parent pair. Construct a small,
deterministic set of bounded intervals enclosing those anchors, optionally
including pure deleted/inserted interior members. Bound flank extension, gaps,
window length, token length, and total verified window pairs `P`. Index anchors
so pair generation itself does not scan all anchor pairs. No arbitrary common
code or cross-parent extension in the initial policy.

Re-normalize each complete window and apply the existing 0.90 whole-sequence
similarity rule. Anchors propose boundaries; they do not prove that intervening
code continues. Require aggregate relocation and review counterexamples.
No exact anchors means this stage may miss a genuinely moved-and-edited run;
state that recall limit rather than falling back to unrestricted search.

With representations capped at `T`, the added LCS verification cost is
O(P T²), with O(T) working rows per comparison, plus representation/retrieval
storage. Deduplicate window pairs and charge every attempted verification to
the budget, including rejected pairs. Report attempted comparisons and cap hits.
Do not verify every prefix while extending, which can silently multiply cost.

## Required tests and acceptance gates

Use existing [source/XML regression suites](../../tests/README.md) and
moveSelectionBench policy contracts. Source pairs check actual srcDiff output;
hand-authored XML isolates membership and adjacency rules. Assert exact
endpoint identities, links, order, membership, and counts, not text-only
presence or a lower total count.

| Case | Required outcome |
| --- | --- |
| Two/three unchanged adjacent statements transfer, same order | One ordered aggregate; individual links retained |
| OpenCV History pair 5: five initial `JacobiSVDImpl_` declarations | One aggregate of five links; stop before unreported `double sd;` |
| Half a block transfers; whole block unavailable/below similarity | Sequence represented without claiming whole-block detection |
| Screenshot permutation `A B C` → `C A B` | Aggregate `A B`, singleton `C`; no whole-run Type-1 |
| Adjacent source members go to separate functions/files | Separate reports |
| Meaningful common or filtered child intervenes on either side | No strict aggregation |
| Adjacent displayed lines belong to different branches/parents | No aggregation |
| Comments, formatting, mixed element kinds, split diff wrappers | Same declared structural adjacency, where reliable |
| Nested conditional/function carries children | No duplicate covered units; preserve parent selection |
| Balanced repeats, unequal cardinality, repeated window identities | No invented pairing |
| Stationary line shift or edit produces delete/insert neighbors | Adjacency cannot establish relocation |
| Sequence-wide consistent identifiers/literals | Stage 2a whole-window Type-2c evidence |
| Locally consistent but globally inconsistent/non-injective renames | Reject Type-2c classification; no relabeling to force acceptance |
| Interior statement added/removed during relocation | Stage 1 splits; Stage 2b assesses whole window under threshold |
| Reordered/gapped sequence beyond threshold | Preserve smaller reports; no threshold relaxation |
| Competing parent/sequence/member proposals | Atomic conflict enforcement, deterministic child fallback |
| Missing context, preprocessor boundaries, nested opposite ownership | Conservative exclusion with diagnostic reason |
| Large sibling lists, repeated content, deep nesting | Explicit bounded generation/verification, deterministic output |

Stage 1 must leave the original selected links and old summaries identical
across normal, diagnostic, and results-only modes. Partition invariants:
every aggregated member belongs to exactly one aggregate; no aggregate crosses
a barrier; both endpoint orders advance by exactly one. Stage 2 must retain
mode agreement, containment rules, and known negative expectations.
The two existing `warp_in_place` Type-3 failures remain known failures until
their separate policy fix; do not change their oracles to make checks green.

Build/test in the Docker workspace using the parent wrapper and existing
Makefile targets, e.g. `./bin/srcml-dev-shell make -C srcMove test-source` and
`./bin/srcml-dev-shell make -C srcMove test-move-selection`; follow with the
appropriate full checks after code changes. Current verification is recorded
below; this document's proposed stages are not implemented merely because they
appear in the plan.

Measure baseline/candidate runtime and peak memory with the existing
[performance runner](../../performance/README.md) over identical fixed XML.
Include large sibling lists and ambiguous repetitions, not only easy examples.
Record added metadata, windows, verifications, cap hits, and output changes.
Agree on acceptable overhead before adopting detector changes; complexity
bounds alone do not establish acceptable practical cost.

## Thesis and evaluation handling

The data is not automatically unusable. Existing runs remain evidence for
their recorded binary/configuration and reported-construct units. They cannot
support a count of independent developer actions. A sequence count is another
declared reporting unit, not retrospective ground truth.

Preserve all frozen source judgments, artifacts, executable provenance, and
old result counts. For Stage 1, replay the same inputs and add a separate
sequence analysis; if saved outputs lack structural metadata, regenerate with
the identified toolchain rather than guessing adjacency from text/lines.
Do not replace earlier outputs or silently reinterpret their columns.

For Stage 2, rerun affected fixed evaluations into new output locations and
fresh History analysis state. Review changed sequence endpoints. Existing
adjudications are bound to output indices/hashes and cannot be transferred
blindly to new groups. Keep the original target inventory and denominators.
Development examples used to tune the rules are development evidence.

BigMoveBench's complete-fragment detection and Chapter 7's reviewed-target
detection remain distinct from sequence aggregation. A cluster of statements
inside a method does not become detection of that complete method. Retain those
scores, and add sequence-level grouping measures against separately reviewed
sequence boundaries. Do not change an oracle solely to improve outcomes.

If only Stage 1 is completed before submission, describe it as a reporting
extension and retain the old detector evaluation. If Stage 2 changes detection,
either evaluate the new detector or clearly retain the older implementation's
results as such. Update architecture/terminology/source-ledger records only
when the implemented behavior and evidence are settled.

## Adversarial review and handoff

Three agents examined algorithm design, counterexamples, and thesis/evaluation
evidence. The algorithm and adversarial reviewers exchanged objections and
replies about the changed-sequence stage. Their converged recommendation is
the staged design above, not evidence of algorithm correctness.

Rejected first approaches: grouping by nearby lines; merging arbitrary
connected components; flattening ordered links into repeated content groups;
inheriting Type-2c from member labels; unrestricted all-subrange/all-pair LCS;
beam search before simpler windows have been evaluated; reducing counts as
the success criterion.

Stage 1 adds revision-specific direct-child metadata and strict chaining after
selection. The canonical implemented contract is now in
[architecture](../architecture.md#ordered-move-sequences); the compound consumer
slice uses that producer-defined projection in History and the browser.
Stage 2 remains a separate decision, with caps and relocation policy made
concrete before coding. User handles all Git staging/commits.

## Stage 1 verification record

Implementation started from checkout `f48236f` on the user's current branch.
A Docker baseline build produced executable SHA-256
`4716608701992a1104a34c6dc1280cb290dea6aea9287aff714147296aad2561`.
The baseline and candidate were run on all 41 existing XML fixtures and the
saved OpenCV comparison 5 XML. All 42 original JSON payloads (excluding the
three new top-level sequence fields) and annotated XML bytes were identical.
The real five-declaration run formed one sequence with the exact ordered member
IDs recorded in the source ledger. The comparison retains 71 atomic groups;
its additive output contains 13 sequences and 40 sequence reporting units.
Those are implementation observations, not revised historical ground truth.

Fifteen new semantic tests pass in Docker, covering grouping, reordering, gaps,
comments/whitespace, directives, raw text, nested opposite ownership, distinct
parents/files, repeated groups, member identity, and output-mode agreement.
Generated baseline/candidate artifacts, receipts, the preservation script and
`preservation.json` are retained locally under the ignored
`benchmark-results/adjacent-sequence-slice1-20261005/` directory. The original
History snapshots and reviewed study were not changed.

The standard `make test` run passed existing XML, source, and policy regressions,
the C++ component checks, 134 BigMoveBench unit tests, 21 selection contracts,
and nine performance-runner unit tests. It exposed an existing snapshot-test
import error, fixed by using its package-qualified helper import. The complete
core Python unit suite then passed all 231 tests. The move-selection unit suite
retains its two documented `warp_in_place` failures (`affine_worker` and
`affine_try`); their source oracles were not changed. The full suite therefore
is not claimed to be entirely green.

Four synthetic stress workloads (128/1,024 ordered and reversed declarations)
preserved all atomic JSON/XML output. Ordered workloads formed one sequence;
reversed workloads formed none. `stress-correctness.json` retains those checks.
The existing performance runner compared the captured baseline and candidate
with one warmup and six interleaved measured repetitions per workload, seed
20261005, declared warm OS cache, annotated XML plus JSON and profiling enabled.
The isolated development run produced these medians:

| Workload | Baseline time (s) | Sequence time (s) | Baseline peak RSS (MiB) | Sequence peak RSS (MiB) |
| --- | ---: | ---: | ---: | ---: |
| OpenCV comparison 5 | 0.6961 | 0.6958 | 34.22 | 34.13 |
| Ordered 128 declarations | 0.0613 | 0.0606 | 8.90 | 9.25 |
| Ordered 1,024 declarations | 0.4341 | 0.4519 | 18.88 | 19.19 |
| Reversed 1,024 declarations | 0.4650 | 0.4643 | 18.81 | 19.04 |

All 48 measured attempts succeeded. These small development workloads do not
establish general scaling or population performance. The isolated run is at
`performance/performance/runs/isolated-baseline-v-sequence/` under the local
verification directory above; its manifest, raw attempts, and summary identify
binary hashes, schedules, resource measurements, and environment. An earlier
run (`baseline-v-sequence`) overlapped correctness checks and is not the basis
for this table. Candidate executable SHA-256 is
`b7aa1d160210e64f9ff2d0f34a038b243e0d3dbd240ddbe37879d25204df8fbf`.

## Compound reporting verification record

The compound projection and conservative malformed-wrapper barriers were
reviewed independently during implementation. Seventeen sequence tests and
13 barrier tests cover all three output modes, partitions, exact member
links, partial source runs, reordering, ambiguity, and adjacency boundaries.
The final complete core Python unit suite passed 251 tests. The authoritative
History suite passed 174 tests; later focused checks covered report/CLI output
and malformed IDs. Legacy source/XML/policy regressions, BigMoveBench's 134
unit tests, C++ components, 21 selection contracts, and nine performance
runner tests passed. The two known `warp_in_place` Type-3 source-oracle
failures remain unchanged.

The same 42 fixed inputs used for Stage 1 retain byte-identical annotated XML
and identical original JSON fields after excluding the six additive sequence
and reporting fields. Primary reports partition their atomic groups exactly
once. The retained OpenCV comparison 5 contains 71 atomic groups and 40 primary
reports. Four 128/1,024-statement ordered/reversed workloads preserve atomic
JSON/XML; ordered runs report once and reversals remain separate.

Artifacts and scripts are under the ignored local
`benchmark-results/compound-reporting-slice2-20261005/` directory. Candidate
executable SHA-256 at verification is
`0071be20208611f4926228fd4ca72479098239cbc879247cfe593d8a6ed7c9dd`.

An exploratory development timing check compared the retained Stage-1 binary
against the compound binary with one warmup and six seeded interleaved
repetitions per variant/workload, declared warm OS cache, XML/JSON output,
and profiling enabled. All 36 measured attempts succeeded. Other local viewer
services remained running; this is not a controlled population experiment.

| Workload | Stage-1 median (s) | Compound median (s) | Stage-1 peak RSS (MiB) | Compound peak RSS (MiB) |
| --- | ---: | ---: | ---: | ---: |
| OpenCV comparison 5 | 0.7224 | 0.7660 | 34.34 | 34.25 |
| Ordered 1,024 declarations | 0.4785 | 0.5133 | 19.20 | 19.05 |
| Reversed 1,024 declarations | 0.4856 | 0.5060 | 19.02 | 18.89 |

These small development workloads show approximately 4–7% median runtime
overhead in this run and similar peak memory, not general performance bounds.
The manifest, raw attempts, and summary are retained at
`performance/performance/runs/stage1-v-compound/` beneath that verification
directory. Projection serializes additional primary endpoint/text arrays, so
output sizes increase even though matching and selection are unchanged.

Final consumer verification passed 260 srcDiffVisual backend tests against the
rebuilt native executable and 72 frontend
tests, backend lint, TypeScript checks, and the production build. Two additional
complete artifact pipeline tests passed for standalone and archive inputs,
including primary counts, retained member IDs, ordered source/destination node
arrays, and access to atomic details. The in-app browser connection was
unavailable, so visual inspection is not claimed; automated UI checks and the
live API provide the consumer evidence. The rebuilt-native checks exposed and
resolved a compatibility issue with annotations inherited from input XML:
these remain separate, unclassified records outside the producer report
partition, whose validation remains strict.

OpenCV was regenerated for the same 210 adjacent pairs with the verified
compound binary: 183 compared pairs, 27 without analyzable changes, zero
failures. The original 341 atomic groups remain (292 Type 1, 13 Type 2c,
36 Type 3); the primary view reports 241 moves (192 Type 1, 13 Type 2c,
36 Type 3). The previous checksum-bound analysis was archived beside the
repository's active `.srcmove` directory. The exported immutable snapshot is
`thesis-workspace/data/srcMove-history/opencv/6c753bd2088d197276dee74bfe09c4fedcbb8471c6353473c6257e0b5f6fdd03.zip`.

After the final viewer rebuild and service restart, the live API published
OpenCV pair 5 as artifact `e7dc778df12940c1bf6a257f45e4a8db`: History and the
artifact agree on 40 primary reports from 71 atomic groups. A five-member
compound detail retains five source nodes, five destination nodes, five raw
texts per side, and accessible atomic details. The receipt is
`live-api-verification.json` in the local verification directory above.
