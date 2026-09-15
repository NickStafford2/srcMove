# Reference Repositories

This directory holds independent, ignored Git clones used for history studies,
performance workloads, and implementation reference. Only this README and
[`repositories.json`](repositories.json) belong to srcMove's Git history.

Recommended benchmark inputs:

| Name | Purpose |
| --- | --- |
| `sqlite` | Focused C history and scaling studies over `src/` |
| `notepadpp` | Medium C++ history studies |
| `opencv` | Large C++ history and stress workloads |
| `linux` | Optional very-large history workloads over `kernel/sched/` |

Reference-only implementations:

| Name | Purpose |
| --- | --- |
| `Deckard` | Tree-based clone-detection reference |
| `SourcererCC` | Token-based clone-detection reference |
| `gumtree` | AST matching and edit-script reference |
| `Open-NiCad` | Clone-detection framework reference |

`make history-scaling CASE=<name> ...` clones a missing registered repository
unless `OFFLINE=1` is supplied. Experiment records must use and preserve exact
commit hashes; the mutable clones are not research evidence and are not Git
submodules of srcMove.
