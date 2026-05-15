# vai-core

A minimal, layered agent runtime built around deterministic boundaries, canonical actions, and introspected skills.

## Layer Responsibilities

- core — single-step LLM loop; produces exactly one action per iteration.
- policy — runtime limits, retries, modes, and behavioural constraints.
- governance — schema generation, validation, canonicalisation, and invariants.
- caching — action templates, fingerprints, and macro-action sequences.
- execution — tool routing, parallelism, aggregation, and result handling.
- skills — pure Python functions introspected into tool schemas.
- ws — IO boundaries: LLM clients, storage, network, external services.
- util — shared helpers and primitives with no business logic.
- config — declarative definitions for LLMs, agents, and runtime settings.

## Core Invariants

- The core loop produces one action per LLM call.
- No multi-step plans are generated or executed.
- All actions must be canonicalised before caching or execution.
- Skills must be pure functions with no side effects or LLM calls.
- Schemas are runtime-generated, never hand-written.
- The runtime is deterministic at boundaries and probabilistic only inside the LLM.