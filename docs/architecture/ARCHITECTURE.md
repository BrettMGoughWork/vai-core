## Project Structure

This layout is organised around a clear separation of concerns:
- **Core runtime + abstractions**
- **Execution and governance**
- **Capabilities and skills**
- **Observability and policy**
- **Tooling and enforcement layers**

Each directory defines a *bounded responsibility*. Avoid cross-cutting logic outside intended layers.

---
```
config/                 # S1 - Runtime configuration files (YAML/JSON/env overrides)
main.py                 # S1 - CLI entrypoint (bootstraps config → agent → execution)

src/
  core/                 # Fundamental abstractions and shared runtime primitives
    agent/              # S5 - Agent orchestration (main control loop, lifecycle)
    config/             # S1 - Typed config models + loaders/validators
    llm/                # S1 - LLM interfaces and transport layer (no business logic)
      providers/        # S1 - Concrete LLM provider implementations (OpenAI, etc.)
    planning/           # S2 - Planning strategies (task decomposition, sequencing)
    types/              # S1 - Core shared types (pure, dependency-free)
      errors/           # S1 - Error models and exception hierarchy
      validation/       # S1 - Input/output validation utilities

  execution/            # S1 - Execution engine
                        # - Runs a *single selected skill*
                        # - Enforces execution contract and lifecycle
                        # - No planning, only execution

  governance/           # S1 - Guardrails and decision constraints
                        # - Tool/skill selection boundaries
                        # - Safety and policy enforcement hooks

  observability/        # S1 - Structured logging and trace emission
                        # - No business logic
                        # - Designed for debugging + monitoring

  policy/               # S1 - Runtime policy hooks
                        # - Extendable rules applied during execution
                        # - Complements governance (more dynamic/custom)

  primitives/
    runtime/            # S3 - Capability discovery and filtering
                        # - Ranking, scoring, and selection helpers
                        # - Defines *what can be done*, not *how to do it*

                        # S3 - Primitive implementations (atomic units of work)
    standard/           # S3 - Built-in, maintained primitive set
    custom/             # S3 - User/plugin-defined primitives (extension point)

  skills/
    library/            # S3 - markdown instruction sets
    custom/             # S3 - custom instruction sets
    registry/           # S3 - registration of skills

  telemetry/            # S1 - Metrics and usage reporting hooks
                        # - Performance, cost, and usage tracking

tests/
  unit/                 # Isolated unit tests (fast, no external deps)
  integration/          # End-to-end and cross-module tests

util/                   # S1 - General-purpose helpers (keep minimal and stateless)
                        # Prefer placing logic in core or features when possible

tools/                  # Developer tooling and enforcement scripts
  code_analysers/           
    shared/             # S1 - Shared analyser utilities
    stratum1/           # S1 - S1 invariant enforcement (strict, foundational rules)
    planning/adapters/  # S2→S3 boundary adapter

---

## Architectural Guidelines

### 1. Layer

```md
# Architecture Overview

This repository is structured around a modular agent runtime, with clear separation between planning, execution, governance, and supporting systems.

## Root

- `config/`  
  Runtime configuration files (models, providers, environment settings).

- `main.py`  
  CLI entrypoint. Responsible for bootstrapping the application, loading config, and invoking the agent runtime.

---

## Source (`src/`)

### Core

Fundamental building blocks for the agent system.

- `core/agent/`  
  Agent runtime orchestration (main control loop, lifecycle management).

- `core/config/`  
  Configuration models and loaders. Handles parsing, validation, and normalisation of runtime config.

- `core/llm/`  
  LLM abstraction layer (interfaces, shared types, request/response handling).

  - `providers/`  
    Concrete implementations for different LLM providers (e.g. OpenAI, Azure, local models).

- `core/planning/`  
  Planning logic: transforms user intent into executable plans or steps.

- `core/types/`  
  Shared domain types used across the system.

  - `errors/`  
    Standardised error definitions and handling strategy.

  - `validation/`  
    Input/output validation utilities and schemas.

---

### Execution

- `execution/`  
  Execution engine responsible for running plans.

  Includes:
  - Execution contracts/interfaces
  - Single-skill executor logic
  - Step orchestration and result handling

---

### Governance

- `governance/`  
  Decision layer for:
  - Tool/skill selection
  - Guardrails and safety constraints
  - Enforcement of execution policies

---

### Capabilities & Skills

- `primitives/runtime/`  
  Capability discovery and ranking:
  - "Skill" filtering
  - Relevance scoring
  - Built-in capability definitions

- `primitives/`  
  Executable primitive skills used by the agent.

  - `standard/`  
    Built-in, supported primitive skills shipped with the system.

  - `custom/`  
    Extension point for user-defined or plugin-based primitive skills.

- `skills/`
  Markdown skill instruction sets used by the agent.

  - `library/`
    Built-in, supported library of skill instructions shipped with the system.

  - `custom/`
    Extension point for user- or agent-defined or plugin-based instruction sets

  - `registry/`
    Registration logic that defines allowed instruction sets
---

### Policy

- `policy/`  
  Runtime policy hooks:
  - Pre/post execution checks
  - Custom enforcement logic
  - Dynamic behavioural overrides

---

### Observability

- `observability/`  
  Structured logging and diagnostics:
  - Log formatting
  - Context propagation
  - Debug support

---

### Telemetry

- `telemetry/`  
  Metrics and instrumentation:
  - Usage tracking
  - Performance data
  - External telemetry integrations

---

## Tests

- `tests/unit/`  
  Fast, isolated tests for individual components.

- `tests/integration/`  
  End-to-end and cross-module tests validating system behaviour.

---

## Utilities & Tooling

- `util/`  
  Shared helper functions and utilities (non-domain-specific).

- `tools/`  
  Developer tooling and static analysis utilities.

  - `code_analysers/`  
    Code analysis tools used to enforce architectural rules.

    - `shared/`  
      Common logic used by analysers.

    - `stratum1/`  
      CLI tools enforcing **S1 invariants** (low-level architecture rules).

    - `planning/adapters/`  
      CLI tools enforcing **S2 invariants** (higher-level architectural constraints).

---

## Design Principles

- **Separation of concerns**: Planning, execution, and governance are strictly isolated.
- **Extensibility**: Skills and providers can be added without modifying core logic.
- **Observability-first**: All major flows should be traceable via logs and telemetry.
- **Policy-driven behaviour**: Runtime behaviour can be modified without changing execution logic.

---

### Cognitive Contract (Stratum‑1 ↔ Stratum‑2 Interface)

1. Purpose

The Cognitive Contract defines the pure, deterministic, side‑effect‑free interface between:

- Stratum 1 — execution, tools, environment, effects  
- Stratum 2 — reasoning, planning, classification, cognition  

Stratum 2 must behave as a pure function:

`
PureInput → PureCognition → PureOutput
`

No execution, no tool calls, no environment access, no mutation.

---

2. Inputs Provided to Stratum 2

Stratum 2 receives exactly three pure, deterministic inputs.

2.1 StepState (current cognitive state)

A frozen, JSON‑pure object containing:

- step_id
- parent_id
- cognitive_input
- last_result
- status
- created_at (logical time)
- attempt
- trace
- canonical_hash

This is the only state Stratum 2 may read.

---

2.2 Last StepResult (optional)

If the previous step produced a result, Stratum 2 receives:

- outcome
- reason
- payload
- trace
- canonical_hash

Always pure and immutable.

---

2.3 Memory Snapshot (read‑only)

A pure JSON structure representing:

- long‑term memory  
- working memory  
- episodic memory  
- agent configuration  
- tool metadata  

Memory is read‑only.  
Stratum 2 cannot mutate memory; it may only propose memory updates via structured outputs.

---

3. Outputs Stratum 2 Must Return

Stratum 2 must return exactly one of the following pure objects.

3.1 Classification

Used when the cognitive step is complete.

`json
{
  "type": "classification",
  "outcome": "success|failure|tool_needed|continue",
  "reason": "string",
  "payload": {}
}
`

---

3.2 Subgoal

A single atomic cognitive objective.

`json
{
  "type": "subgoal",
  "goal": "string",
  "context": {}
}
`

---

3.3 Segment

A multi‑step cognitive unit.

`json
{
  "type": "segment",
  "steps": [],
  "context": {}
}
`

---

3.4 Plan

A hierarchical plan.

`json
{
  "type": "plan",
  "root": {},
  "nodes": [],
  "metadata": {}
}
`

---

3.5 Structured Error

Stratum 2 never throws exceptions; it returns structured errors.

`json
{
  "type": "error",
  "error_type": "validation|planning|classification|unknown",
  "message": "string",
  "details": {}
}
`

Stratum 1 decides how to handle errors.

---

4. Purity & Side‑Effect Rules

Stratum 2 must obey the following constraints.

4.1 No execution

Stratum 2 cannot:

- call tools  
- run code  
- perform I/O  
- access environment state  

---

4.2 No side effects

Stratum 2 cannot mutate:

- StepState  
- memory  
- global state  
- external systems  

Trace is allowed but must be pure JSON.

---

4.3 Pure function requirement

Given identical inputs, Stratum 2 must produce bit‑identical outputs.

This is enforced by:

- deterministic StepState  
- deterministic StepResult  
- deterministic OutcomeClassifier  
- canonical hashing  
- purity validation  

---

5. Allowed Input/Output Shapes

Stratum 2 may only read/write:

- dict  
- list  
- str  
- int  
- float  
- bool  
- null  

No custom objects, classes, functions, datetimes, or bytes.

Everything must be JSON‑pure.

---

6. Contract Summary

Stratum 2 is a pure cognitive engine.

It receives:

- StepState  
- Last StepResult  
- Memory snapshot  

It returns exactly one:

- classification  
- subgoal  
- segment  
- plan  
- structured error  

It must not:

- execute tools  
- mutate memory  
- perform side effects  
- depend on environment state  

It must be pure, deterministic, and replayable.