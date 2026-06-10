# StepSpec Contract v1.0

**Source:** `src/core/planning/contracts/step_spec.py`
**Class:** `StepSpec` (frozen dataclass)
**Version constant:** `CURRENT_STEP_SPEC_VERSION = "1.0"`

## Purpose

Describes a single step in a plan before it reaches the executor. This
is a planning-time artifact — it does not carry execution state (that
lives in `StepState`).

## Schema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `intent` | `str` | ✅ | — | Natural-language description of what this step does |
| `args` | `Dict[str, Any]` | ❌ | `{}` | Input arguments keyed by parameter name |
| `target_skill` | `str \| None` | ❌ | `None` | Skill name (may be resolved at execution) |
| `expected_output` | `Dict[str, Any] \| None` | ❌ | `None` | Schema hint for output forwarding |
| `fallback_strategies` | `List[str]` | ❌ | `[]` | Fallback skill names in preference order |
| `version` | `str` | ❌ | `"1.0"` | Contract version identifier |

## Validation Rules

1. `intent` must be non-empty string.
2. `args` must be a `dict`.
3. `version` must be non-empty string.

## Serialization

- `to_dict()` → JSON-compatible dict (omits fields at their defaults to
  keep output lean).
- `from_dict()` → reconstructs from serialized dict.
- `from_llm_step()` → constructs from raw LLM output dictionary
  (accepts `description`/`intent`, `inputs`/`args`, `capability`
  variants).

## Properties

- `has_fallback: bool` — `True` if at least one fallback strategy is defined.
- `has_target_skill: bool` — `True` if a specific skill was targeted.

## Cross-Stratum Usage

- **S2→S1:** Executor reads `args` and `target_skill` to invoke the
  correct capability.
- **Planner→Executor boundary:** Steps are produced by the planner,
  optionally have `expected_output` schemas for inter-step data flow.
- **Repair boundary:** Broken steps are compared against their StepSpec
  to detect drift.
