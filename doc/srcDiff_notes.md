# srcDiff behavior notes

## Nested revision states

srcDiff stores both revisions in one well-formed XML document. Its diff
elements therefore act as revision-membership states rather than independent,
flat edit records:

| Nearest enclosing state | Content belongs to |
| --- | --- |
| no diff element | both revisions |
| `diff:common` | both revisions |
| `diff:delete` | original revision only |
| `diff:insert` | modified revision only |

The nearest state wins. A nested tag changes the state inherited from its
parent. There is no two-level format limit; elements may nest as deeply as the
structured comparison requires, subject to ordinary well-formed XML nesting.

Explicit `diff:common` is primarily needed when shared code is structurally
inside a larger inserted or deleted construct. For example, when an `if`
wrapper is removed but its body survives, srcDiff can encode the old `if` in an
outer deletion and the surviving body in nested common markup. Removing the
outer deleted form for the modified revision must promote the common descendant
rather than discard it.

Nested opposite-revision elements similarly let one combined tree switch
between old and new structural forms. A `diff:insert` physically nested in a
`diff:delete` does not mean that new source was inserted into deleted source;
it means that the combined XML changed from describing the old form to the new
form. Same-revision nesting does not change revision membership, although inner
boundaries or attributes may retain separate structural or move information.

This behavior comes from representing two overlapping srcML trees in one XML
tree. Understanding the shortest-edit-script implementation is not required to
consume the format. The edit algorithm helps choose correspondences; nested
markup serializes those correspondences while preserving both revisions.

For srcMove, clone similarity alone is insufficient: candidate construction
must first respect these revision states. The implemented candidate policy is
documented in [Architecture](architecture.md#implemented-pipeline); remaining
design questions belong in the
[move-detection redesign](plans/move_detection_redesign.md).
