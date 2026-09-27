# Code conventions

- Prefer simple functions with explicit inputs and returned outputs. Minimize
  mutation of caller-owned objects and other hidden side effects.
- Prefer enums for closed internal state sets. Use strings at serialization and
  command-line boundaries where stable textual values are part of the contract.
- Prefer composition over inheritance. Do not introduce application-domain
  class hierarchies. Inheritance is acceptable when required or strongly
  encouraged by a language or library interface, such as deriving exceptions
  from `std::exception`.
- Establish correct, deterministic behavior before optimizing. Require current
  profiling evidence before adding performance complexity.
- Format C++ with the repository's `.clang-format` configuration.

These are implementation preferences, not substitutes for the verified
behavior and constraints in [Architecture](architecture.md) and the repository
[agent guidance](../AGENTS.md).
