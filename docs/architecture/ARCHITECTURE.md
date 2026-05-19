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

  capabilities/         # S3 - Capability discovery and filtering
                        # - Ranking, scoring, and selection helpers
                        # - Defines *what can be done*, not *how to do it*

  skills/               # S3 - Skill implementations (atomic units of work)
    standard/           # S3 - Built-in, maintained skill set
    custom/             # S3 - User/plugin-defined skills (extension point)

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
    stratum2/           # S2 - S2 invariant enforcement (higher-level guarantees)

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

- `capabilities/`  
  Capability discovery and ranking:
  - Skill filtering
  - Relevance scoring
  - Built-in capability definitions

- `skills/`  
  Executable skills used by the agent.

  - `standard/`  
    Built-in, supported skills shipped with the system.

  - `custom/`  
    Extension point for user-defined or plugin-based skills.

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

    - `stratum2/`  
      CLI tools enforcing **S2 invariants** (higher-level architectural constraints).

---

## Design Principles

- **Separation of concerns**: Planning, execution, and governance are strictly isolated.
- **Extensibility**: Skills and providers can be added without modifying core logic.
- **Observability-first**: All major flows should be traceable via logs and telemetry.
- **Policy-driven behaviour**: Runtime behaviour can be modified without changing execution logic.

---

## Guidance for Contributors (Copilot-aware)

When making changes:

- Prefer extending within existing modules before introducing new top-level folders.
- Maintain clear boundaries:
  - Planning never executes
  - Execution never decides *what* to run
  - Governance never performs execution
- Add new skills under `skills/standard` or `skills/custom`, not in core logic.
- Keep all provider-specific logic inside `core/llm/providers`.
- Ensure new features include:
  - Types (`core/types`)
  - Validation where applicable
  - Unit + integration tests
- Update this file if responsibilities or boundaries change.

