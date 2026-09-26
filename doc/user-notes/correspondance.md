# New way of thinking about the problem

## Two Separate problems

### Correspondence
Type (1,2,3) matcher can establish:

```
```
    OLD foo()  ←────────→  NEW foo()
                  correspondence
```


At this point, you still haven't detected a move.
You've only established that these two pieces of code appear to represent the same code across revisions.

### Classification
Now a second algorithm examines that correspondence and classifies it:
```


```
                 correspondence
                       │
          ┌────────────┼────────────┐
          ↓            ↓            ↓
    stationary     relocated      copied
          ↓
    restructured
          ↓
      ambiguous
```

```
```
