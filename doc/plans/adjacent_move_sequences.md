# Adjacent moved sequences

Status: proposed, October 5, 2026. No detector changes or experimental results
are established by this plan. Code inspected at srcMove
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

### The screenshot is a reordered sequence

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

Use a separate sequence record, proposed shape:

```text
sequence_id
member_move_ids: [p, q, ...]       # explicit selected 1:1 links, in order
from: {file, parent, members: [...ordered endpoints...]}
to:   {file, parent, members: [...ordered endpoints...]}
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
O(N) traversal work and O(N) retained metadata in the conservative bound.
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
appropriate full checks after code changes. No build/tests were needed for
this planning-only document.

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

The next implementation task is Stage 1 only: establish the source/XML test
oracles, add revision-specific direct-child metadata, implement strict chaining,
then finalize additive sequence output and verify original report preservation.
Stage 2 is a separate decision after those results, with caps and relocation
policy made concrete before coding. User handles all Git staging/commits.
