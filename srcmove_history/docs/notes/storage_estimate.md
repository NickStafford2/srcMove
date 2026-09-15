# Storage Estimate

The first-order storage model is:

```text
analysis storage ~=
    number of commit pairs
  * average persisted result per pair
  + small fixed metadata
  + Git objects kept reachable by the retention ref
```

The average persisted result depends on the frozen retention policy and the
frequency of moves and failures. Measure representative repositories before
using this estimate for capacity planning.
