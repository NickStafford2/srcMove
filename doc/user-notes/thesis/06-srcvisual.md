# Chapter 6: srcVisual

> Draft status: first-pass thesis prose. Statements about the current system are
> based on the srcVisual project documentation. The evaluation described in
> Section 6.7 is proposed and has not yet been executed. Bracketed placeholders
> must be replaced with frozen evidence before submission.

## 6.1 Contribution and chapter scope

srcMove writes its findings into a structured XML document. That representation
is appropriate for preserving program structure and machine-readable links, but
it is not an effective primary interface for inspecting a detected move. A
reader must otherwise interpret XML namespaces, locate deletion and insertion
regions, resolve their relationship, recover the corresponding source text,
and determine which file owns each endpoint. The task becomes more difficult
when the source and destination belong to different files because no single
local source view contains the complete relationship.

srcVisual addresses this inspection problem. It is a companion application for
srcDiff and srcMove rather than a second move detector. Its contribution is to
turn the final annotated document into coordinated XML, tree, source, diff, and
move views. These views expose the same underlying data through representations
suited to different questions: what annotation was written, where it occurs in
the structured tree, what source text it covers, and how its endpoints relate.

This distinction limits the claims made in this chapter. srcVisual can make a
detector result inspectable and can support manual analysis, but the interface
does not establish that a detection is correct. Unless a human-subject study is
performed, this thesis will not claim that srcVisual improves comprehension,
reduces task time, or is more usable than another interface.

## 6.2 The visualization problem

The input to srcVisual is not merely a pair of text files. A srcDiff document
contains structured program units and difference annotations, while a
srcMove-annotated document additionally connects regions that participate in a
move. Three forms of context must remain aligned during inspection:

1. **Document context:** the XML element, attributes, and structural position
   that encode a change.
2. **Source context:** the original or modified file, source span, and nearby
   unchanged code needed to interpret that change.
3. **Relationship context:** the other endpoint or endpoints of the detected
   move, potentially in another file.

A raw XML viewer supplies the first context but makes the other two expensive
to reconstruct mentally. A conventional two-pane textual diff supplies local
source context but does not naturally expose structured annotations or
many-to-many move relationships. A source-only presentation may also conceal
whether a confusing display was caused by the detector or by a mismatch among
the visualization's own derived data.

srcVisual is therefore organized around a consistency requirement rather than
around a particular widget. Every pane must be derived from the same final,
pruned, annotated dataset. If a file unit or XML tag survives into one view,
its corresponding tree and source representation must survive into the other
views. This invariant makes the application useful for detector inspection:
disagreement among panes should not introduce a second, interface-created
interpretation of the analysis result.

**Literature task:** connect this problem to prior work on software-evolution
visualization, structural differencing interfaces, and coordinated multiple
views. Add primary citations here; do not infer an empirical benefit for
srcVisual from findings about a different interface.

## 6.3 System architecture

srcVisual currently consists of a Python/Flask backend and a React frontend.
The backend accepts pasted or uploaded srcDiff XML, including documents that
already contain srcMove annotations. It then prepares the information needed
by the browser interface. According to the current application contract, the
backend can:

- extract original and modified source through `archive_reader`;
- invoke `srcdiff --position` when position information is absent;
- invoke `srcMove` when move annotations are absent; and
- construct a normalized payload containing the annotated XML, move results,
  file metadata, recovered source, and tree data.

The backend's intermediate files are execution details, not part of the data
model exposed to the user. Temporary filenames and paths must not replace the
real filenames carried by the input document. This is particularly important
for a single-file srcDiff unit whose `filename` value identifies the original
and modified files as a pair. Treating that metadata as a temporary output path
would corrupt file ownership and consequently the interpretation of moves.

Position enrichment has another preservation obligation. When srcVisual adds
positions to a srcDiff document, the result should differ from the input only
by the required position information. Existing tags, attributes, ordering, and
content are not disposable input to a reconstruction. They are analysis data
that must survive the enrichment step. Similarly, when move annotations are
already present, they are the source of truth for visualization rather than a
request to silently rerun the detector and substitute a new answer.

The normalized payload is the boundary between backend processing and frontend
presentation. The frontend uses that payload to render all views, avoiding a
design in which each pane independently parses or filters a different version
of the input. Figure 6.1 should make this boundary explicit.

> **Figure 6.1 placeholder — srcVisual data flow.** Input srcDiff/srcMove XML
> enters the backend; optional source extraction, position enrichment, and move
> annotation produce one final annotated dataset; pruning occurs once; payload
> construction supplies the XML, tree, source, diff, and move views. The figure
> should distinguish conditional tool invocations from operations performed on
> every request.

## 6.4 Input shapes and data invariants

srcVisual supports both archive-style srcDiff documents with nested file units
and single-root file-unit documents. Supporting both shapes is necessary
because file ownership is represented differently in the two forms, yet the
frontend requires a uniform way to associate source spans and move endpoints
with files. Archive inputs also allow one analysis to contain several changed
files, which is the form needed to inspect a cross-file move as one coherent
result.

The following invariants define correct visualization behavior:

- final annotated XML metadata determines file and unit identity;
- generated temporary names never appear as source identity in returned XML;
- position generation preserves all non-position content of the input;
- archive and single-root documents remain supported input forms;
- original/modified filename pairs remain valid metadata for single-file
  inputs;
- file ownership and unit order survive processing; and
- pruning precedes final payload assembly so every pane represents the same
  retained units and tags.

These are stronger and more testable requirements than a statement that the
interface "looks correct." They define observable relationships among the
input document, backend output, and rendered views. They also separate a
visualization defect from a srcMove defect: if the final XML contains a move
but one pane omits its file or endpoint, the inconsistency belongs to
srcVisual; if every pane faithfully displays an incorrect annotation, the
candidate issue lies in the upstream analysis or its interpretation.

## 6.5 Coordinated views and move-centered interaction

The XML view provides direct access to the representation emitted by srcDiff
and srcMove. The tree view exposes its structural organization without
requiring the reader to navigate raw markup. Source-code and diff views restore
the textual surroundings that give an isolated structured region meaning. The
move view gathers relationship information so that the user can inspect a
detection as a group rather than as unrelated deletion and insertion marks.

The important feature is coordination among these views. Selecting a move
should preserve the identity of its source and destination regions as the user
moves between representations. For a within-file move, the two locations may
be separated by enough unchanged code that viewing them together is already
useful. For a cross-file move, coordinated navigation is essential because the
source and destination cannot appear in the same file-local viewport. New-file
moves, deleted-file moves, reordered units, and move groups with multiple
regions further require that the interface preserve direction, cardinality,
file ownership, and unit ordering.

> **Figure 6.2 placeholder — representative cross-file move.** Use one frozen
> srcMove result that contains readable source and destination filenames, a
> selected move group, and visible endpoints. Capture enough of the XML or tree
> view to demonstrate that the relationship comes from the annotated document.
> Record the example artifact, tool revisions, and selection rationale in the
> caption or accompanying replication material.

The final chapter should describe only interactions present in the frozen
srcVisual revision. Features such as bidirectional click navigation, linked
highlighting, or filtering must be verified in the application before they are
stated as current behavior. Until that verification is attached, they remain
candidate details for the screenshot narrative rather than claims in this
draft.

## 6.6 Role in the research workflow

srcVisual supports four parts of the broader research workflow. First, it
supports implementation debugging by showing whether move annotations and
their source spans agree. Second, it supports failure analysis by placing false
or missed relationships in their program context. Third, it supports example
selection for explanatory figures and case studies. Fourth, it communicates
the behavior of srcMove to readers who should not need to decode the full XML
format before understanding one detection.

None of these roles turns manual inspection into an independent oracle. A
researcher who knows the expected result can still misclassify an ambiguous
change, and an attractive synchronized display can make an upstream error
easier to see without proving that it is an error. Examples selected with
srcVisual must therefore remain traceable to their original input, detector
revision, and evaluation record. If the interface is used during benchmark
labeling or manual validation, Chapter 5 or Chapter 7 must state the review
protocol and the number of reviewers rather than citing the visualization as
the validation method.

## 6.7 Evaluation design

This draft proposes an **engineering evaluation** of the artifact. It does not
propose a usability experiment unless a separate human-subject protocol is
designed and approved. The engineering evaluation should test whether the
pipeline preserves its documented invariants and whether declared inspection
scenarios can be completed from the final payload and interface.

### 6.7.1 Research question

The evaluation question is: *Does srcVisual consistently represent supported
srcDiff and srcMove inputs across its XML, tree, source, diff, and move views?*
This question concerns representation fidelity and scenario coverage. It does
not measure human comprehension or efficiency.

### 6.7.2 Scenario matrix

The frozen scenario set should contain, at minimum:

| Dimension | Required cases |
| --- | --- |
| Input structure | archive-style; single-root file unit |
| Position state | positions present; positions absent |
| Move state | move annotations present; move annotations absent |
| Move location | within-file; cross-file |
| File lifecycle | modified file; new file; deleted file |
| Unit relationship | ordinary ordering; reordered units |

Not every combination must be manufactured if it is invalid or redundant, but
every omission should be explained. Each case needs a stable fixture identifier
and an explicit expected set of files, units, and move endpoints.

### 6.7.3 Checks and measures

For each case, compare the input, final annotated XML, normalized payload, and
rendered state. Record whether:

1. non-position input content is preserved during position generation;
2. filenames and original/modified ownership remain correct;
3. the same retained units and tags appear in every applicable pane;
4. move direction and endpoint cardinality agree with final XML metadata; and
5. the declared inspection task can be completed without consulting a hidden
   backend artifact.

Automated tests should cover the data invariants where possible. A scripted or
manually recorded walkthrough can cover the rendered scenarios that cannot be
asserted entirely at the payload boundary. Report pass/fail counts against the
predeclared fixture set, not an informal statement that "several examples
worked."

### 6.7.4 Reproducibility record

Record the srcVisual, srcDiff, srcMove, and `archive_reader` revisions; the
runtime environment; fixture checksums; commands used to run backend and
frontend tests; and the browser used for rendered checks. Store screenshots as
derived evidence linked to those fixtures. A screenshot by itself is not a
test result because it does not establish the provenance or completeness of
the displayed data.

## 6.8 Results

No srcVisual evaluation results are asserted in this draft.

> **Results placeholder.** Insert the frozen scenario matrix, automated test
> results, any manually verified rendering checks, and references to retained
> artifacts. State the denominator for every count. Separate backend invariant
> failures, frontend rendering failures, and unsupported cases. Do not report a
> usability score or comprehension improvement without a corresponding study.

The results narrative should identify which invariants were demonstrated and
which remain assumptions. Representative screenshots can then illustrate the
validated behavior, but should not replace the result table.

## 6.9 Limitations and future work

srcVisual depends on the structure and metadata produced by srcDiff and
srcMove. It can expose those results, but it cannot recover semantic evidence
that the upstream tools never produced. Its supported input forms and source
languages are also bounded by the surrounding toolchain. The proposed
engineering evaluation establishes consistency only for the declared fixture
space; it does not establish performance on arbitrarily large inputs or
benefits to human users.

The current application is a local development system. The hosted application
described by the project is a future vision. A public service that accepts
untrusted XML or repositories would invoke native analysis tools on
user-controlled data and therefore requires a threat model, isolation,
resource limits, input limits, and operational hardening. Repository selection,
commit retrieval, and safe multi-user execution must not be described as
current capabilities until implemented and evaluated.

Potential future evaluation could compare task correctness and completion time
for raw XML inspection against srcVisual, but such a study would require
defined participants, tasks, comparison conditions, consent procedures, and an
analysis plan. Until then, the defensible contribution is the implementation
and verification of a consistent, move-centered visualization pipeline.

## Evidence still required

- [ ] Add primary literature for structural-diff and software-evolution
  visualization.
- [ ] Freeze a scenario corpus and record fixture checksums.
- [ ] Verify the exact interaction set in the selected srcVisual revision.
- [ ] Produce the backend/frontend data-flow figure.
- [ ] Capture a publication-quality cross-file example.
- [ ] Execute the engineering evaluation and replace the results placeholder.
- [ ] Record tool revisions and environment details in replication material.

Current technical behavior should be checked against the
[srcVisual README](../../../../srcVisual/README.md) and
[application rules](../../../../srcVisual/docs/Rules.md).
