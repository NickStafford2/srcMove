# Move-detection redesign

Status: active implementation. Revision ownership, conservative mixed-region
rejection, multi-scale construct retention, unified evidence proposals, and
deterministic utility selection are implemented. Approximate Type-3 retrieval,
contextual ambiguity resolution, and a general hierarchy optimizer remain
planned; the current selector includes a local parent-versus-descendant bundle
comparison.

This is the canonical design and implementation plan for revising srcMove's
candidate semantics, Type-3 retrieval, pair ranking, and hierarchical move
selection. The verified current pipeline remains documented in
[`doc/architecture.md`](../architecture.md). The
[`deckard/`](deckard/README.md) plan is an experimental structural-similarity
track within this larger design, not a replacement for the full move detector.

## Objective

Report the largest complete source construct that is exclusively deleted at
one location, exclusively inserted at another, and supported by sufficiently
strong and unambiguous evidence. Fall back to smaller child moves when a parent
does not form a coherent match. Preserve srcDiff membership semantics,
deterministic output, cross-file matching, explainable evidence, and bounded
time and space costs.

The redesign separates three questions that the current evidence-ordered
pipeline partially conflates:

1. **Candidate correctness:** what source material was actually deleted or
   inserted, and which complete constructs are eligible move units?
2. **Pair evidence:** how strongly does one deletion correspond to one
   insertion?
3. **Global selection:** which non-overlapping set of pairs best explains the
   changed material?

A clone or similarity algorithm contributes to the second question. It cannot
by itself answer the first or third.

## Why the current policy needs revision

The production stream currently recognizes `diff:delete` and `diff:insert`,
tracks their parent/child nesting, and defaults to a `leaf_only` policy. Opening
a nested insert or delete releases the parent candidate-construction state.
This bounds retained work, but it also makes the deepest diff region eligible
before matching establishes whether a larger construct is the real move.

Three related limitations follow:

- A same-side nested region causes the parent to be discarded even when the
  entire parent is a complete, coherent moved construct.
- `diff:common` is not represented as a revision-membership boundary. Common
  text can enter the raw and canonical content of an outer deletion or
  insertion even though that text did not disappear or appear.
- Exact matches are selected before Type-2 and Type-3 edges exist. A small
  exact child can therefore suppress a larger, strong near-match parent.

These are different problems. Replacing `leaf_only` with `top_level_only` would
not solve them: it would admit broad mixed wrappers that contain common or
opposite-side material.

## Mental model

### Revision ownership

For each substantive source event, its effective owner is determined by the
nearest enclosing srcDiff state:

| Effective state | Membership |
| --- | --- |
| no explicit diff wrapper | both revisions |
| `diff:common` | both revisions |
| `diff:delete` | original revision only |
| `diff:insert` | modified revision only |

Nesting is a state transition, not evidence that a new fragment is literally
inside deleted source code. The closest state overrides the surrounding state.

### Move versus clone

Similarity is necessary but insufficient. A move requires evidence that a
fragment disappeared at a source location and appeared at a destination
location. Similar content that remains at the source is a copy or repeated
clone, not a move. srcDiff membership supplies the disappearance/appearance
boundary; clone detection supplies correspondence evidence.

### Maximality

The desired unit is not always the outermost wrapper or the deepest leaf. It is
the largest **valid matched construct**:

- If an entire deleted block and inserted block match strongly, prefer one
  block move over several child-statement moves.
- If the parent is mixed, weak, or has no coherent destination, allow its
  complete children to match independently.
- Never report both a selected parent and descendants that explain the same
  evidence unless the output model explicitly introduces hierarchical moves.

## Candidate semantics

### Region-state summary

Replace the single `has_diff_child` decision with a summary that records, for
each candidate boundary:

- its governing side: deletion or insertion;
- whether substantive descendants are same-side, opposite-side, or common;
- substantive token and construct counts for each state;
- parent and child candidate identifiers;
- whether the boundary is a complete permitted srcML construct;
- whether it contains a pre-existing move annotation; and
- source span, XPath, file identity, and structural kind.

Whitespace-only transitions should not make an otherwise coherent construct
mixed. Purity decisions must use substantive source events.

### Eligibility rules

Use hard rules before similarity or scoring:

1. `diff:common` is never exclusive moved payload. It may be retained as
   context but must not contribute to deleted/inserted payload size or identity.
2. Opposite-side material is a candidate boundary. An insertion nested in a
   deletion can be evaluated independently, but the mixed outer wrapper is not
   automatically one atomic move.
3. Same-side nesting does not automatically invalidate a parent. A nested
   delete inside a delete preserves old-side ownership; likewise for insertion.
4. Default candidates must be complete permitted constructs at statement or
   larger granularity. Fragment mode may expose smaller units explicitly.
5. Candidates must contain a minimum amount of substantive, nontrivial
   evidence.
6. Candidate pairs must have compatible structural kinds and size ranges before
   expensive similarity work.

The first conservative implementation may reject any outer candidate with
substantive common or opposite-side descendants. A later implementation may
use common material as context, but it must not count it as moved payload.

### Multi-scale alternatives

Retain legitimate alternatives rather than choosing a level during parsing:

```text
function candidate
  block candidate
    statement candidate
    statement candidate
```

The candidate count should remain proportional to eligible syntax constructs,
not to every arbitrary token interval. Parent/child identifiers allow selection
to resolve alternatives after pair evidence exists.

## Pair generation and similarity

All match methods should produce edges in one sparse candidate graph:

```text
deleted candidate -- evidence --> inserted candidate
```

Type 1, Type 2, and Type 3 are evidence classes on edges, not irrevocable
selection passes.

### Type 1

Use exact canonical hashing for retrieval and confirm equality with the full
canonical identity. Hash equality alone remains insufficient.

### Type 2

Use consistent identifier mapping and literal categories. Preserve the
candidate's structural kind and ambiguity cardinality. Exact normalized
identity supplies strong evidence but does not override candidate maximality by
itself.

### Type 3

Type-3 detection should have two distinct components:

1. **Approximate retrieval:** find a small set of plausible partners using
   structural partitions, size windows, and fingerprints or approximate-neighbor
   indexing.
2. **Pair verification:** calculate the declared sequence, vector, tree, or
   hybrid similarity only for shortlisted pairs.

The current bounded two-row LCS is a valid verifier and uses linear auxiliary
space, but its pairwise time is quadratic in the two sequence lengths. Root-kind
and size filters reduce work without removing its worst-case large-bucket
Cartesian product.

Deckard-style characteristic vectors and locality-sensitive hashing are
candidate approaches for structural retrieval and similarity. They should be
evaluated as components against the current sequence representation. They do
not replace revision ownership, candidate eligibility, move-versus-copy rules,
or overlap selection.

## Confidence, utility, and selection

### Do not call an uncalibrated score a probability

Initially expose an interpretable confidence or ranking score. A number can be
described as `P(move)` only after calibration against a declared labeled
population and validation on held-out data. Synthetic BigMoveBench cases can
tune thresholds and support probability calibration for that benchmark domain;
they cannot alone establish historical-move probabilities.

### Separate pair confidence from selection utility

**Pair confidence** asks how credible one correspondence is. Candidate features
include:

- exact, consistently normalized, or near-match evidence class;
- continuous Type-3 similarity and bidirectional coverage;
- structural-kind and subtree-shape agreement;
- candidate information size;
- uniqueness and number of competing partners;
- revision purity and candidate completeness; and
- weak contextual or locality evidence.

Type-1, Type-2, and Type-3 evidence must not be naively added because they are
correlated. An exact pair is also maximally similar under weaker
representations. Preserve a match class plus its relevant continuous evidence.

**Selection utility** asks whether choosing that pair best explains the change.
A useful starting form is:

```text
utility = confidence * matched_substantive_tokens
          - edit_penalty * unmatched_tokens
          - ambiguity_penalty
          - fragmentation_penalty
```

This lets a large 92%-similar function outrank a tiny exact child when the
larger edge explains far more evidence, without claiming that 92% is more
similar than exact equality.

### Feature guidance

- Content similarity is the dominant signal.
- Matched evidence size helps distinguish a meaningful construct from a short,
  frequently repeated statement.
- Uniqueness is important: a repeated exact fragment can be weaker evidence of
  one particular move than a unique near-match.
- Structural compatibility should be a cheap gate and a confidence feature.
- Raw line or file distance should be a weak prior or tie-breaker. Strong
  locality penalties would conflict with cross-file and long-distance moves.
- Context, such as enclosing construct identity and neighboring rare tokens,
  may disambiguate repeated candidates better than raw distance.
- Revision impurity should normally be an eligibility failure, not a small
  penalty that unrelated features can overcome.

### Global selection

Select a non-overlapping set of edges subject to:

- each one-to-one candidate is used at most once unless copy/repeat semantics
  are explicitly selected;
- selected source spans do not explain the same deleted evidence twice;
- selected destination spans do not explain the same inserted evidence twice;
  and
- a selected parent suppresses descendants that cover the same evidence.

For a parent and its matched descendants, compare:

```text
utility(parent edge)
```

with:

```text
sum(utility(compatible child edges)) - fragmentation penalty
```

Start with deterministic greedy selection over a sparse edge set plus a local
parent-versus-children replacement pass. Pursue a more expensive optimizer only
if evaluation demonstrates a material error attributable to greedy selection.

## Performance design

Let `N` be the number of eligible candidates and `K` the number of shortlisted
pair edges. The target is to keep `K` sparse rather than construct every
deletion-by-insertion pair.

### Staged retrieval

Use cheapest evidence first:

1. exact canonical hash index;
2. Type-2 normalized hash index;
3. structural-kind partition;
4. size-ratio window;
5. rare token, shingle, winnowing, MinHash, LSH, or characteristic-vector
   retrieval;
6. bounded top-`k` plausible partners per candidate;
7. expensive Type-3 verification; and
8. final confidence and utility calculation.

Distance, size, kind, purity, and ambiguity features are constant-time or
amortized-constant-time once metadata is cached. The dominant costs should be
candidate representation, approximate retrieval, and Type-3 verification.

### Space discipline

Retaining parents must not copy every XML event or canonical string into every
open ancestor. In deeply nested input, that can approach
`O(events * nesting_depth)` work and storage.

Prefer:

- one shared token/event arena per file or unit;
- candidate references to ranges or compact subtree summaries;
- compositional hashes and fingerprints computed once per syntax node;
- a stack of lightweight region-state summaries;
- parent/child candidate IDs rather than copied subtrees; and
- early abandonment of expensive representations for semantically ineligible
  mixed candidates.

Measure actual candidate counts, edge counts, representations retained, LCS
calls, and peak memory before claiming an asymptotic improvement.

## Deckard's role

Deckard maps syntax subtrees to characteristic vectors and searches for nearby
vectors rather than performing an exhaustive tree comparison. That makes it a
valuable baseline for structural Type-3 retrieval and possibly verification.

Do not replace the whole pipeline with Deckard. Preserve these srcMove-specific
stages around any Deckard-derived component:

```text
srcDiff ownership
  -> valid multi-scale move candidates
  -> structural representation and sparse retrieval
  -> pair verification and evidence
  -> hierarchical move selection
  -> annotation and results
```

The faithful Deckard-style experiment should be evaluated alongside the
current LCS representation. Its vector abstraction may improve scalable
retrieval while losing ordering or identifier-correspondence information that
the current representation preserves. Treat that tradeoff as an empirical
question.

## BigMoveBench tuning and evaluation

BigMoveBench is suitable for:

- comparing Type-3 representations and retrieval recall;
- tuning similarity thresholds and top-`k` retrieval limits;
- testing parent-versus-child candidate policies;
- measuring whole-fragment versus incidental-child detection;
- learning or fitting a ranking model; and
- calibrating confidence for the declared synthetic benchmark domain.

It is not, by itself, historical move ground truth. A calibrated value learned
from synthetic cases must be described as benchmark-domain calibration. Claims
about the probability of genuine historical developer moves require an
independent, manually reviewed historical dataset or another defensible oracle.

Keep tuning, validation, and final evaluation partitions separate. Record the
dataset release, transformation, feature version, model parameters, threshold,
selection policy, and executable revisions in every frozen run.

## Implementation sequence

### Phase 0: freeze evidence

- Use [`moveSelectionBench`](../../moveSelectionBench/README.md) for focused
  same-side, opposite-side, deep-nesting, `diff:common`, ambiguity, and
  parent-versus-child semantic characterization. Its misses are observations,
  not frozen claims that the current implementation is correct.
- Compare baseline and candidate executables with the same catalog and inspect
  per-case transitions, not just aggregate pass totals.
- Use the existing performance runner over these smoke inputs and larger fixed
  repository workloads. Record runtime, peak memory, candidate counts,
  shortlist entries, pair comparisons, LCS calls, produced edges, and
  selection rejections.
- Continue using BigMoveBench for population-scale detection/classification;
  keep final evaluation separate from threshold and ranking-policy tuning.

### Phase 1: correct revision ownership

- Recognize `diff:common` in the streaming state machine.
- Track effective ownership and substantive state transitions.
- Exclude common and opposite-side material from exclusive move payload.
- Conservatively reject mixed outer candidates while retaining eligible inner
  candidates.

### Phase 2: retain multi-scale candidates efficiently

- Replace the binary `has_diff_child` policy with region-state summaries.
- Preserve same-side complete parents and meaningful children as alternatives.
- Introduce shared representations or compositional summaries so nested
  candidates do not duplicate the stream.

### Phase 3: unify edge generation

- Make exact, Type-2, and Type-3 stages emit edges without immediately
  consuming overlapping candidates.
- Add structural, size, uniqueness, and ambiguity metadata.
- Bound approximate retrieval and report retrieval recall separately from
  verification accuracy.

### Phase 4: score and select

- Add explainable confidence components and selection utility.
- Implement deterministic sparse-edge selection with overlap constraints.
- Add the local parent-versus-children comparison.
- Emit score components and decision reasons in results JSON.

### Phase 5: evaluate representations

- Compare the current bounded-LCS verifier with a faithful Deckard-style
  baseline and any hybrid retrieval design.
- Tune only on declared BigMoveBench tuning partitions.
- Freeze parameters before final evaluation.
- Profile time, peak memory, candidate count, edge count, shortlist recall, and
  end-to-end detection outcomes.

## Required tests

At minimum, cover:

- `delete -> common` and `insert -> common` ownership;
- `delete -> insert` and `insert -> delete` state changes;
- same-side nesting where the parent should win;
- same-side nesting where only children have destinations;
- small exact child versus large strong Type-3 parent;
- mixed parent rejected while eligible inner candidates survive;
- repeated exact fragments and ambiguous partners;
- cross-file moves where distance must not suppress the match;
- top-`k` retrieval recall for known expected pairs;
- deterministic selection under equal scores; and
- equivalence of normal and `--results-only` matching decisions.

## Open decisions

- Which substantive events make a candidate mixed, especially punctuation at
  srcDiff state boundaries?
- Should common material be available only as context or also in a separate
  projected representation?
- Which candidate kinds participate in Type-3 matching?
- What top-`k` limit preserves acceptable retrieval recall?
- How should one-to-many copy/move cases interact with one-use selection?
- Is greedy plus local replacement sufficient, or does evaluation justify a
  hierarchical dynamic program or sparse weighted matching algorithm?
- Which score components are hand-declared, empirically fitted, or calibrated,
  and on which frozen populations?

Do not resolve these questions solely by matching the current regression
outputs. Use focused semantic fixtures, BigMoveBench tuning partitions,
negative examples, and independent performance workloads.
