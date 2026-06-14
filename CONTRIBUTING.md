# Contributing to vai-core

Thanks for contributing.

This guide is the baseline for local setup, folder semantics, strata boundaries, skill additions, and local checks before opening a PR.

## 1) Local setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pytest
```

To run the test suite:

```bash
python main.py
```

## 2) Folder semantics

Use existing folders and keep scope narrow.

- `main.py`: runtime entrypoint and bootstrapping.
- `config/`: model aliases and runtime config.
- `src/runtime/` (S1): execution engine, pipeline, retry/recovery, panic guard, degraded mode.
- `src/strategy/` (S2): planning, memory, task decomposition, cognitive contracts.
- `src/capabilities/` (S3): primitives, skills, registries, safety validators, quarantine.
- `src/platform/` (S4): channels, queue/event substrate, worker pool, supervision, control plane, observability, config, security, daemon, deployment.
- `src/agents/` (S5): agent layer (placeholder).
- `src/workflow/` (S6): workflow engine (placeholder).
- `src/release/`: release checklist and gating.
- `tests/unit/`, `tests/integration/`: test suites.
- `tools/`: developer tooling, testing harness, channels CLIs, quarantine CLI.
- `docs/`: architecture, API, channel, lifecycle, control plane, worker pool documentation.

## 3) Strata overview

Strata boundaries are critical. The system is organised into six strata:

| Stratum | Directory | Responsibility |
|---|---|---|
| **S1** | `src/runtime/` | Execution substrate: pipeline, retry, recovery, panic guard, degraded mode |
| **S2** | `src/strategy/` | Cognitive planning: pure function, no I/O, no side effects |
| **S3** | `src/capabilities/` | Capability orchestration: primitives, skills, registry, quarantine |
| **S4** | `src/platform/` | Universal ingress: channels, queue, worker pool, supervision, config, security, observability, deployment |
| **S5** | `src/agents/` | Agent layer (placeholder) |
| **S6** | `src/workflow/` | Workflow engine (placeholder) |

### Key rules:
- **S4 must not import S2 or S5/S6.** S4 is infrastructure — it cannot depend on cognition or agents.
- **S2 must remain pure.** No I/O, no tool calls, no side effects. Identical inputs → identical outputs.
- **Channels (S4) must not know about workflows or agents.** They are plumbing — they normalize events and push them to the queue.
- **S5/S6 subscribe to S4's event substrate.** They never own transport, never listen on ports.

## 4) How to add a skill

Current skill registration is import-driven via `BaseSkill`.

1. Create or update a skill module under `src/primitives/`.
2. Add a handler function with clear typed args.
3. Instantiate `BaseSkill(...)` with:
   - `name`
   - `description`
   - `handler`
   - `category` (`SkillCategory`)
   - `side_effects` (`SideEffect`)
4. Ensure the module is imported on startup so registration runs.
   - today this can be done by importing the skill module from `main.py` or `src/primitives/__init__.py`.
5. Add/update tests for behavior and validation.

Minimal example:

```python
from src.primitives.runtime.base import BaseSkill
from src.primitives.runtime.categories import SkillCategory
from src.primitives.runtime.side_effects import SideEffect

def add(a: int, b: int) -> int:
    return a + b

math_add = BaseSkill(
    name="math_add",
    description="add two integers",
    handler=add,
    category=SkillCategory.MATH,
    side_effects=SideEffect.NONE,
)
```

## 5) Local checks before PR

Run these commands locally:

```bash
python -m pytest -q
python -m tools.code_analysers.stratum1.cli --root . --strict
python -m tools.code_analysers.deadcode.analyser
```

If your change touches S4 release boundaries, also run the release checklist:

```bash
python -m src.release.checklist
```

If your change is docs-only, still run at least:

```bash
python -m pytest -q
```

## 6) Release checklist

S4 releases are gated by a mandatory checklist defined in `src/release/checklist.py`. The checklist validates:

- **Invariants**: namespace boundaries, purity rules, import acyclicity, schema stability
- **Determinism**: golden snapshot comparison across multiple cycles
- **Safety**: panic guards, poison detection, degraded mode transitions
- **Performance**: throughput, latency, memory, CPU thresholds
- **Concurrency**: deadlock/race detection under load, forced delays
- **Channels**: lossless, ordered, backpressure-safe, timeout-safe
- **Observability**: structured logs, metrics, traces, health checks

Run `python -m src.release.checklist` before any S4 release. Any failure blocks the release.

## 7) Pull request notes

- Keep PRs small and scoped to one issue.
- Link the issue in the PR body (`Closes #<id>`).
- Include what changed and which local checks you ran.
- If you touch architecture boundaries, also update `docs/architecture/ARCHITECTURE.md` or `ROADMAP.md` when needed.
- If you add a new channel, document it in `docs/channels/`.
- If you add a new API, document it in `docs/api/`.
