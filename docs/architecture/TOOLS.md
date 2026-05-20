## Overview
This document describes the internal tooling available in this repository.
These tools are intended to support code quality, architectural consistency, and developer productivity.

All tools are exposed as Python entrypoints under tools.* and are designed to be run directly via python -m.

## Code Analysers
### Dead Code Analysis
```
python -m tools.code_analysers.deadcode.analyser
```
Performs static analysis to identify unused or unreachable code within the codebase.
Behaviour

Scans for:
- Unreferenced functions
- Unused classes
- Dead modules

Helps keep the codebase lean and maintainable

Notes

- The analyser intentionally ignores factory register decorators
- This prevents false positives for dynamically registered components
(e.g. plugin/factory patterns where usage is not statically visible)


## Stratum 1 Invariants Check
```
python -m tools.code_analysers.stratum
```
Validates Stratum 1 invariants across the codebase.

### Purpose 
Ensures that foundational architectural constraints (Stratum 1) are not violated.
### Behaviour

Checks structural and dependency-level invariants
Enforces core layering boundaries and contracts
Helps maintain long-term architectural integrity


## Future Tooling
Additional CLI tools will be introduced over time to support developer workflows and system consistency.
Planned tooling includes:


### Skills scaffolding

Generate boilerplate for new skills/components
Enforce consistent structure and conventions



### Code generation utilities

Reduce repetitive setup for common patterns



### Validation and linting extensions

Expand invariant checks beyond Stratum 1




## Design Principles
All tools in this repository follow these principles:


### Local-first

Tools are designed to run locally without external dependencies



### Fast feedback

Intended for frequent use during development



### Opinionated by design

Enforce conventions rather than merely suggesting them



### Extensible

New analysers and generators should integrate into the same tools.* structure




### Usage Guidelines

- Run analysers regularly during development
- Treat violations as signals, not suggestions
- Prefer fixing root causes rather than suppressing warnings
- Extend tooling when patterns become repetitive