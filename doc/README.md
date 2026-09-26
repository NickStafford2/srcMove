# srcMove Documentation

This directory contains the detailed documentation for srcMove. Start with the
project [README](../README.md) for its purpose, current behavior, prerequisites,
and command-line usage.

## Architecture and behavior

- [Architecture](architecture.md): verified current pipeline, matching behavior,
  output annotations, performance model, and limitations
- [Algorithm flowcharts](diagrams/pipeline_diagram.md): simple thesis overview
  and detailed candidate, matching, and selection decision flow
- [Data structure diagram](diagrams/data_structure_diagram.md): relationships
  among the primary implementation types
- [Scoring model diagram](diagrams/scoring_model_diagram.md): move-selection
  decision model
- [srcDiff notes](srcDiff_notes.md): investigated srcDiff behavior and XML
  format details
- [XPath commands](sample_xpath_commands.md): example queries for srcMove XML
- [srcMove History](../srcmove_history/docs/README.md): architecture
  decision, target-driven runtime, research motivation, and study results

The project README and implementation are authoritative when older research
summaries or diagrams disagree with current behavior.

## Development and testing

- [Code rules](code_rules.md): local implementation conventions
- [Correctness tests](../tests/README.md): test entry points, suite boundaries,
  and fixture conventions
- [Benchmarks](../benchmarking/README.md): benchmark types and runners
- [Performance benchmark](../performance/README.md): repeatable comparisons of
  srcMove builds over fixed srcDiff XML workloads

## BigMoveBench research

- [BigCloneBench and IJaDataset notes](../bigMoveBench/docs/bigclonebench.md): dataset setup,
  terminology, and interpretation
- [BigMoveBench methodology](../bigMoveBench/docs/methodology.md):
  methodology for generating synthetic move cases
- [BigMoveBench runner](../bigMoveBench/README.md): operational
  setup and commands
- [BigMoveBench execution architecture](../bigMoveBench/docs/execution.md):
  database-backed case storage, execution journaling, recovery, and profiling

## Research notes and planned work

- [Move-detection redesign](plans/move_detection_redesign.md): canonical
  proposed semantics, candidate hierarchy, sparse pair scoring, selection,
  performance constraints, and BigMoveBench validation plan
- [Performance optimization status](performance_optimization_strategy.md):
  completed work, remaining opportunities, and evidence required before another
  optimization
- [Deckard experiment](plans/deckard/README.md): proposed structural-vector
  baseline within the broader move-detection redesign
- [Dormant archive parallelism plan](parallel_programming_upgrade_plan.md):
  bounded concurrency design for large multi-file srcDiff archives
- [Backlog](backlog.md): open questions and candidate improvements
- [Active handoffs](handoffs/README.md): narrowly scoped unfinished tasks, when
  any exist
- [Master's thesis working draft](user-notes/thesis/README.md): chapter-level
  prose, research questions, evidence gates, and writing tasks for srcMove,
  BigMoveBench, srcVisual, srcMove History, and performance
- [`user-notes/`](user-notes/): terminology, hypotheses, and other exploratory
  material that does not define current behavior
- [Thesis summary draft](user-notes/thesis-summary-draft.md): preserved thesis
  prose and aspirational research framing; not authoritative implementation
  documentation

## Guidance for AI agents

- [Repository agent guidance](../AGENTS.md): scope, required entry points, test
  rules, and Git constraints
- [Documentation maintenance](ai_documentation_guidelines.md): recursive
  improvement, source-of-truth rules, and the plan/handoff lifecycle

AI agents should use the same architecture, testing, and methodology documents
as human contributors. Agent-specific files define operating constraints, not
an alternative description of srcMove.
