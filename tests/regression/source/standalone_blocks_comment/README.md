# Expected Behavior

Reordering blocks whose only payload is comments does not constitute a source
code move. Comments and whitespace provide no substantive move evidence, so
srcMove reports zero moves.
