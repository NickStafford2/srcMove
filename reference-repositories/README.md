# Reference Repositories

This directory holds independent, ignored Git clones used for history studies,
performance workloads, and implementation reference. The clones are not part
of srcMove's Git history. This README, the registry, and the recovery inventory
are tracked.

## Registry and recovery inventory

[`repositories.json`](repositories.json) is the canonical registry: each entry
maps a stable ID to a checkout folder, clone URL, roles, and optional analysis
scope. Checkout paths are relative to this directory, so `notepadpp` belongs at
`srcMove/reference-repositories/notepadpp/` in the parent workspace. Folder names
are case-sensitive. Registered repositories need not all be installed.

[`recovery-inventory.json`](recovery-inventory.json) records the November 2, 2026
local inventory: which entries were installed, their actual origin URLs,
checked-out full commit IDs and branches, tracked changes, and names of local
`.srcmove*` analysis directories. It is a dated recovery aid, not an experiment
manifest or proof of a GitHub backup. Refresh it deliberately when changing the
set of retained checkouts; experiment manifests remain authoritative for the
revisions used in a particular run.

| Installed folder | Purpose |
| --- | --- |
| `sqlite`, `notepadpp`, `opencv`, `linux` | Main repository-history inputs |
| `zlib` | Smaller history and reviewed source examples |
| `Deckard`, `SourcererCC`, `gumtree`, `Open-NiCad`, `RefactoringMiner` | Reference implementations |
| `srcMove` | Separate historical/reference clone, distinct from the enclosing srcMove development repository |

The registry additionally contains `context_export`, `firefox`, and
`wowy_advanced_analytics`; these were absent at inventory time and are not
required merely to rebuild srcMove. Reference implementation clones are optional
unless reproducing work that uses them.

### Restoring a clone

From the enclosing srcMove repository, use the inventory's `origin` and
registry's `checkout` values:

```bash
git clone <origin-url> reference-repositories/<checkout>
git -C reference-repositories/<checkout> checkout --detach <recorded-commit>
```

Repeat for the repositories needed. A full clone retains history; a shallow
clone may omit revisions needed for history studies. A detached checkout
restores the recorded source revision; create a branch explicitly if continuing
development. The commands above are templates, not a shell script. Remote
availability and reachability of recorded commits were not verified.

The existing Linux clone uses the kernel.org stable Linux remote, while the
registry default is Torvalds' GitHub repository. Use the recorded actual origin
to restore that observed clone. Linux reported 13 modified tracked files;
inspection confirmed that each file exactly matches its differently cased
counterpart in the recorded Git commit, and both spellings resolve to the same
local file inode. These are case-collision checkout artifacts on the Mac's
case-insensitive filesystem, not unique changes requiring backup. For a complete
Linux working tree, clone onto a case-sensitive filesystem such as a Linux
Docker volume; a bind mount of the same Mac directory retains the collision.
The Git object database preserves both committed versions even though the Mac
working tree cannot represent both names independently. Do not commit these
apparent changes or try to fix them by repeatedly restoring individual files.

### What cloning does not restore

Local `.srcmove`, `.srcmove-archive-*`, and other `.srcmove*` directories contain
analysis state and are not supplied by upstream clones. The inventory records
their names only. Preserve needed evidence exports in the private thesis
workspace; preserve live state separately if resuming it matters. Also review
local changes, untracked files, stashes, and local-only commits before calling
a clone disposable. This inventory did not audit those categories beyond the
reported tracked working-tree changes.

## Uses

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
| `RefactoringMiner` | Refactoring-detection reference |

`make history-scaling CASE=<name> ...` clones a missing registered repository
unless `OFFLINE=1` is supplied. Experiment records must use and preserve exact
commit hashes; the mutable clones are not research evidence and are not Git
submodules of srcMove.
