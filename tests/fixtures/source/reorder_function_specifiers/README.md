# Goal

The moved declaration should take precedence over its reordered type-specifier
fragments. The specifier order does not change behavior, and isolated `long`,
`signed`, and `int` matches are not useful source-code moves.

# Current Behavior

The source pair moves a member declaration while also changing the order of
equivalent type specifiers. This exercises hierarchical selection on srcDiff's
nested move representation.
