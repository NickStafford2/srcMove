# Reference Repositories

This directory holds independent, ignored Git clones used for history studies,
performance workloads, and implementation reference. Only this README and
[`repositories.json`](repositories.json) belong to srcMove's Git history.

Recommended repositories:

| Name | Purpose |
| --- | --- |
| `sqlite` | Focused C history and scaling studies over `src/` |
| `notepadpp` | Medium C++ history studies |
| `opencv` | Large C++ history and stress workloads |
| `linux` | Optional very-large history workloads over `kernel/sched/` |
| `Open-NiCad` | Clone-detection implementation reference |

`make history-scaling CASE=<name> ...` clones a missing registered repository
unless `OFFLINE=1` is supplied. Experiment records must use and preserve exact
commit hashes; the mutable clones are not research evidence and are not Git
submodules of srcMove.
