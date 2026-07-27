Here is how srcMove currently decides what counts as a move.

Pipeline
run_pipeline() does this in src/pipeline.cpp:107:

1. Parse every diff:insert / diff:delete region from the srcDiff XML.
2. Filter those regions into move candidates.
3. Group candidates by canonical content.
4. Prefer exact matches.
5. Try limited Type-2 matches for eligible unmatched candidates.
6. Annotate any group with at least one delete and one insert.

What “Leaf-Only” Means
Leaf-only is defined in src/region_filter.cpp:225:

keep = !r.has_diff_child;

That means: keep only diff:insert / diff:delete regions that do not contain another diff:insert or diff:delete.

It does not mean AST leaf nodes. It means leaf in the nested srcDiff region tree.

So if srcDiff emits this shape:

<diff:delete>
...
<diff:delete>real changed thing</diff:delete>
...
</diff:delete>

The outer delete is not a leaf, because it has a diff child. The inner delete is a leaf and can become a move candidate.

Default Filters
Default options are in src/region_filter.cpp:260:

- policy = leaf_only
- drop_whitespace_only = true
- skip_pre_marked = false
- expand_structural_children = true
- min_chars = 2

So srcMove normally ignores whitespace-only regions and regions with fewer than 2 raw characters.

One subtle point: skip_pre_marked = false, so already-marked srcDiff moves are still considered candidates. The writer avoids overwriting existing move attributes, but these regions can still affect grouping.

Structural Child Expansion
After a leaf diff region passes leaf-only, srcMove may split it into preferred child candidates before using the whole region.

That happens in src/region_filter.cpp:149.

Preferred child candidate names include:

- structural constructs: function, function_decl, class, struct, enum, namespace, import
- statements: decl_stmt, expr_stmt, return, if_stmt, for, while, do, switch, try, break, continue, goto, throw

If a leaf diff wrapper contains one or more of those direct child subtrees, srcMove emits those child subtrees as candidates and does not emit the whole wrapper as a candidate.

That is important: leaf-only picks the diff wrapper, then expand_structural_children may replace that wrapper with function/statement candidates.

Exact Matching
Candidates are first grouped by canonical_text, not raw text.

Canonicalization is in src/parse/canonical_subtree.cpp:50. By default it:

- ignores outer diff:insert / diff:delete wrapper
- ignores diff:ws
- ignores whitespace-only text nodes
- keeps tags and non-whitespace text

So formatting-only whitespace differences usually do not prevent an exact match, but comments, literals, operators, names, and structure still matter.

Type-2 Matching
After exact matches are used, unmatched candidates may get a Type-2 match in src/move_registry/content_group_builder.cpp:211.

Type-2 uses type2_canonical_text, which normalizes <name> text outside <type> elements.

But Type-2 is intentionally restricted. Eligible roots are in src/region_filter.cpp:67:

- structural constructs: function, function_decl, class, struct, enum, namespace, import
- selected statements: decl_stmt, if_stmt, for, while, do, switch, try

Notably, Type-2 does not apply to plain return, expr_stmt, operators, member-access fragments, literals, or type names. There are tests guarding those false-positive cases.

Also, Type-2 groups are only accepted when they are one-to-one:

if (!is_one_to_one(group)) continue;

So ambiguous Type-2 many-to-one or many-to-many candidates are discarded.

What Becomes an Annotated Move
A content group becomes a move if it has at least one delete and one insert. Annotation happens in src/writer/annotation_plan.cpp:107.

The output gets one UUID per group. If a group has multiple deletes/inserts, they share the same move id; move_pair_count is only estimated as min(delete_count, insert_count).

My Read
The current behavior is conservative in some places and aggressive in one place:

- Conservative: leaf-only avoids matching large srcDiff wrapper hunks when nested smaller diffs exist.
- Conservative: Type-2 is limited to statement-level-or-larger constructs and only one-to-one groups.
- Aggressive: expand_structural_children = true means a leaf diff wrapper can be split into multiple statement/function candidates, which can report child moves instead of one larger moved block.

That last point is probably the main thing to review if you are thinking about “what sort of blocks should count as moves.”
