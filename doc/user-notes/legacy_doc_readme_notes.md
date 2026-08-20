# Legacy Design Notes from `doc/README.md`

These exploratory notes were moved from the former documentation index when it
was converted into a navigation page. They are preserved as historical research
context and do not describe authoritative current behavior.

## Early implementation outline

- Pass 1: create objects that store information about moves and surrounding
  context.
- Analyze all potential moves as a possible extension point for future tools.
- Pass 2: mark moves and add attributes.
- Consider Type-1 and Type-2 moves.

## Developer expectations

Move detection should consider how developers understand changelogs, impact
tracing, and refactoring operations. False positives are undesirable, and the
definition of a clone can be subjective. Open questions included whether users
care primarily about a change in code location, a change in behavior, or both.

Candidate idiomatic operations included:

- moving a complete construct to a new file
- moving a complete construct within a file
- alphabetizing lines
- moving a single line or comment
- formatting and whitespace changes
- moving function parameters across lines
- requiring compatible source and destination syntactic categories

## Possible move attributes

The original notes considered attributes for Type-1 and Type-2 moves,
formatting changes, move identifiers, moves to new files, destination paths,
filenames, XPath locations, syntactic categories, and partner relationships.

One possible namespaced representation was:

```text
srcmove:id="..."       # stable id
srcmove:path="..."     # XPath-like query path
srcmove:file="..."
srcmove:kind="insert|delete"
srcmove:pair="..."     # optional matching partner id
srcmove:hash="..."     # optional subtree signature
```

An XPath example shared for eye-tracking work was:

```xpath
//src:unit[@filename='_data/EL_A_CS_NI/edge_ratio_2.py']/src:function[@pos:start='14:1' and @pos:end='75:0']/src:block[@pos:start='14:66' and @pos:end='75:0']/src:block_content[@pos:start='14:67' and @pos:end='75:0']/src:expr_stmt[@pos:start='15:5' and @pos:end='29:7']/src:expr[@pos:start='15:5' and @pos:end='29:7']/src:literal[@pos:start='15:5' and @pos:end='29:7']
```

The accompanying Qt sketch built paths from element names, filenames, and
`pos:start`/`pos:end` attributes. It was an input to the design discussion, not
the current srcMove XPath specification.

## Open srcDiff questions

- Why does srcDiff create nested `diff:insert` and `diff:delete` elements?
- Why are `diff:ws` elements frequent throughout srcDiff output?
