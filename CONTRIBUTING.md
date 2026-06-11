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
- `src/core/`: agent loop, config, llm transport/providers, shared types, planning contracts.
- `src/runtime/`: execution engine and retry/safety runtime behavior.
- `src/governance/`: tool and policy guardrails.
- `src/primitives/runtime`: tool specs, registry, schema generation, filtering/ranking.
- `src/primitives/`: skill implementations.
- `src/skills/`: skill instruction sets (markdown)
- `src/observability/`, `src/telemetry/`, `src/policy/`: logging, telemetry hooks, runtime policy hooks.
- `tests/unit/`, `tests/integration/`: test suites.
- `tools/architecture/`: architecture extraction, auditing, and CI checks.
- `docs/architecture/`: architecture and roadmap docs.

## 3) Strata overview

Strata boundaries are important in this repo.

- Stratum 1: execution substrate. deterministic runtime and invariants.
- Stratum 2: cognitive planning layer. pure state transitions and planning primitives.
- Stratum 3: skills/capability orchestration and extension points.
- Stratum 4+: distributed/runtime expansion phases in roadmap.

When you change code, keep logic in its stratum and avoid cross-layer leakage.

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

If your change is docs-only, still run at least:

```bash
python -m pytest -q
```

## 6) Pull request notes

- Keep PRs small and scoped to one issue.
- Link the issue in the PR body (`Closes #<id>`).
- Include what changed and which local checks you ran.
- If you touch architecture boundaries, also update `docs/architecture/ARCHITECTURE.md` or `ROADMAP.md` when needed.
