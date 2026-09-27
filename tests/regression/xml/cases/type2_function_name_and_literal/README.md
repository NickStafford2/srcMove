# Type-2 normalization contract

The `get_port`/`get_timeout` name and numeric-literal substitutions retain a
Type-2 correspondence despite potentially different semantics.
Neither fixture provides reliable mapped location context, so the correspondence
is `ambiguous/insufficient_context` and produces no move annotation. This is not
a claim of stationarity or semantic equivalence.

The [normalization diagnostic contracts](../../../../../moveSelectionBench/type2_normalization_contracts.json)
preserve the endpoint paths and text independently of move output.
