# AGENTS.md

Guidance for AI agents working in this repository.

## Work Style

- Start small. Prefer one inspectable step over a large hidden change.
- Read the relevant code and docs before making assumptions.
- Keep edits scoped to the user's request.
- Do not overwrite or revert user changes unless explicitly asked.
- Report generated files, ignored files, and commands you ran.

## Documentation

Follow [AI Documentation Guidelines](doc/ai_documentation_guidelines.md).

In short: improve documentation when you learn something useful, but write each
durable fact once in the correct place. Link to the canonical doc instead of
repeating the same information.

This checkout is normally developed inside the parent `srcMLBuildTemplate`
workspace, not as a standalone tree. The canonical workspace layout,
dependency order, and Docker/macOS workflow are documented in the parent
workspace at `../docs/workspace.md`.

## Testing

- Use existing test runners and fixture patterns when possible.
- For BigCloneBench work, start with Type-1 clone pairs only.
- Type-3 and Type-4 moves are not supported.
- Keep generated benchmark suites separate from small hand-authored tests.

## Useful Entry Points

- [README.md](README.md): project overview and build/run basics
- [../docs/workspace.md](../docs/workspace.md): parent workspace layout,
  sibling repositories, build order, and Docker/macOS workflow
- [doc/README.md](doc/README.md): documentation index
- [doc/technical_summary.md](doc/technical_summary.md): implementation overview
- [doc/bigclonebench_notes.md](doc/bigclonebench_notes.md): BigCloneBench setup notes
- [doc/bigclonebench_srcmove_conversion.md](doc/bigclonebench_srcmove_conversion.md):
  converting BigCloneBench clone pairs into srcMove tests
- [test/README.md](test/README.md): test entry points and suite boundaries

## Git

The user will handle all git commit and staging work.
