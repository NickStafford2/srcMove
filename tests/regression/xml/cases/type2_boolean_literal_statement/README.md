# Boolean Literal Type-2 Case

This fixture currently follows the classic syntactic Type-2 definition:
replacing one Boolean literal with another Boolean literal is classified as a
Type-2 move in delete/insert context.

Changing `false` to `true` can change program behavior, so this fixture is also
a useful future policy boundary. A stricter move definition could require
semantic or historical continuity evidence beyond normalized syntax. That
policy is not part of the current Type-2 classifier.
