# AGENTS.md

Guidance for AI agents working in this repository.

## Repository Boundary

`srcMove` is an independent Git repository. It may be checked out as
`srcMLBuildTemplate/srcMove` beside `srcReader`, `srcDiff`, and `srcML-install`,
but its parent and siblings are separate repositories or generated dependency
paths. Do not treat them as part of srcMove or edit them unless the task
explicitly includes workspace integration.

[README.md](README.md) is the canonical srcMove build and dependency guide. When
this checkout is embedded in SrcMLBuildTemplate, the parent's
`docs/workspace.md` is the canonical guide to the surrounding scaffold.

## Work Style

- Start small. Prefer one inspectable step over a large hidden change.
- Read the relevant code and docs before making assumptions.
- Keep edits scoped to the user's request.
- Do not overwrite or revert user changes unless explicitly asked.
- Report generated files, ignored files, and commands you ran.

## Documentation

Follow [Documentation Maintenance and Recursive
Improvement](doc/ai_documentation_guidelines.md).

In short: improve documentation when you learn something useful, but write each
durable fact once in the correct place. Link to the canonical doc instead of
repeating the same information.

Thesis drafts, reference papers, and working notes belong in the independent
private `../thesis-workspace/` repository, not in srcMove. Keep verified srcMove
behavior and research-method documentation here so thesis claims can cite a
stable technical source.

This checkout is normally developed inside the parent `srcMLBuildTemplate`
workspace, not as a standalone tree. The canonical workspace layout,
dependency order, and Docker/macOS workflow are documented in the parent
workspace at `../docs/workspace.md`.

## Testing

- Use `make build` and `make test` as the public developer entry points.
- Use `tests/run.py` directly only for test inventory or case-level selection.
- Use existing test runners and fixture patterns when possible.
- For BigCloneBench work, start with Type-1 clone pairs only.
- Type-3 is an observational recall stratum; Type-4 moves are not supported.
- Keep generated benchmark suites separate from small hand-authored tests.

## Versioning

Before finishing a release-worthy change, review the canonical
[versioning policy](README.md#versioning) and update [`VERSION`](VERSION) in the
same change when appropriate.

- During `0.x` development, normally increment the minor version for new
  behavior, meaningful algorithm changes, or changes to reported results.
- Use a patch increment for a narrowly compatible correction that does not
  intentionally change the detector's behavior contract.
- Reserve a major increment for an explicitly approved, substantial breaking
  milestone; do not infer a major release merely because an implementation is
  large.
- Documentation, tests, refactors, and internal tooling alone do not require a
  version increment.
- Treat `VERSION` as the single source of truth; do not duplicate the version
  number in source or build files.

## Useful Entry Points

- [README.md](README.md): project overview and build/run basics
- [Makefile](Makefile): canonical build and test commands
- [doc/README.md](doc/README.md): documentation index
- [doc/architecture.md](doc/architecture.md): verified srcMove implementation overview
- [srcmove_history/docs/README.md](srcmove_history/docs/README.md):
  repository-history analyzer architecture, runtime, and research notes
- [bigMoveBench/docs/bigclonebench.md](bigMoveBench/docs/bigclonebench.md): BigCloneBench setup notes
- [bigMoveBench/docs/methodology.md](bigMoveBench/docs/methodology.md):
  converting BigCloneBench clone pairs into srcMove tests
- [tests/README.md](tests/README.md): test entry points and suite boundaries
- [benchmarking/README.md](benchmarking/README.md): benchmark types and entry points

## Git

The user will handle all git commit and staging work.
