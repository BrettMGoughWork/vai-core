`vai-core` is a clean, deterministic agent runtime built for clarity and long-term maintainability.

It’s built around a small set of stable concepts — models, capabilities, skills, and a safety substrate — that keep the system predictable even as you extend it.

The core idea is simple: give LLMs structured jobs, not free rein. The runtime forces clean JSON output, mediates all external calls through a strict capability system, and bakes in safety, observability, and self-healing by default.
Core Concepts

Models — pure data shapes. Everything the system moves around is strongly typed.
Capabilities — declare what the agent can do (read files, make requests, etc), without giving it direct access.
Skills — small, focused behaviours that combine prompts, guardrails, and logic on top of capabilities.
Safety Substrate — the runtime’s guardrails. It controls execution, handles panics, manages degraded modes, and keeps things stable.

Repository Layout

src/core/ — core types and contracts
src/primitives/ — reusable building blocks
src/skills/ — reusable agent behaviours
src/runtime/ — the execution engine
docs/architecture/ — deep technical docs

