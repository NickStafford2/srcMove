# srcMove Documentation

This directory contains the detailed documentation for srcMove. Start with the
project [README](../README.md) for its purpose, current behavior, prerequisites,
and command-line usage.

## Architecture and behavior

- [Technical summary](technical_summary.md): research-oriented system summary,
  current benchmark context, and major limitations
- [Pipeline diagram](diagrams/pipeline_diagram.md): one-page view of the
  processing stages
- [Data structure diagram](diagrams/data_structure_diagram.md): relationships
  among the primary implementation types
- [Scoring model diagram](diagrams/scoring_model_diagram.md): move-selection
  decision model
- [srcDiff notes](srcDiff_notes.md): investigated srcDiff behavior and XML
  format details
- [XPath commands](sample_xpath_commands.md): example queries for srcMove XML

The project README and implementation are authoritative when older research
summaries or diagrams disagree with current behavior.

## Development and testing

- [Code rules](code_rules.md): local implementation conventions
- [Correctness tests](../tests/README.md): test entry points, suite boundaries,
  and fixture conventions
- [Benchmarks](../benchmarks/README.md): benchmark types and runners

## BigCloneBench research

- [BigCloneBench and IJaDataset notes](bigclonebench_notes.md): dataset setup,
  terminology, and interpretation
- [Converting BigCloneEval into srcMove tests](bigclonebench_srcmove_conversion.md):
  methodology for generating synthetic move cases
- [BigCloneBench runner](../benchmarks/bigclonebench/README.md): operational
  setup and commands

## Planning and non-authoritative notes

- [Backlog](backlog.md): open questions and candidate improvements
- [`user-notes/`](user-notes/): thesis outlines, terminology, hypotheses, and
  other exploratory material that does not define current behavior
- [Notes migrated from the former documentation index](user-notes/legacy_doc_readme_notes.md):
  historical design questions preserved when this file became an index

The files under `handoffs/` contain temporary or historical task state. They
are not canonical documentation; verified findings should be incorporated into
the relevant document above.

## Guidance for AI agents

- [Repository agent guidance](../AGENTS.md): scope, required entry points, test
  rules, and Git constraints
- [AI documentation guidelines](ai_documentation_guidelines.md): how to record
  durable discoveries without creating duplicate sources of truth

AI agents should use the same architecture, testing, and methodology documents
as human contributors. Agent-specific files define operating constraints, not
an alternative description of srcMove.
