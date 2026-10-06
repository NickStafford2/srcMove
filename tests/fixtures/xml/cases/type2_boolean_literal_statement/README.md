# Type-2c normalization contract

Replacing `false` with `true` retains a Boolean-literal Type-2c correspondence.
Neither fixture provides reliable mapped location context, so the correspondence
is `ambiguous/insufficient_context` and produces no move annotation. This is not
a claim of stationarity or semantic equivalence.

The [normalization diagnostic contracts](../../../selection/type2_normalization_contracts.json)
preserve the endpoint paths and text independently of move output.
