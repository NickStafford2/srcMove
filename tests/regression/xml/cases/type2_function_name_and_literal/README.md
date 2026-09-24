# Function Name and Literal Type-2 Case

This fixture currently follows the classic syntactic Type-2 definition: a
consistent function-name substitution plus replacement of one numeric literal
by another numeric literal is classified as a Type-2 move in delete/insert
context.

The pair (`get_port` returning `8080` and `get_timeout` returning `30`) is also
a useful future policy boundary. Its normalized syntax matches, but its names
suggest that stronger semantic or historical continuity evidence could reject
it under a stricter move definition. That possible policy is not part of the
current Type-2 classifier.
