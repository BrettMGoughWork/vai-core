# AgentPlan Contract v1.0

**Source:** `src/core/planning/contracts/agent_plan.py`
**Class:** `AgentPlan` (frozen dataclass)
**Version constant:** `CURRENT_CONTRACT_VERSION = "1.0"`

## Purpose

The canonical representation of a complete plan produced by Stratum 2.
This is the single source of truth for plans crossing S2↔S1 and S2↔S3
boundaries. Combines `Plan` content with `PlanMemoryRecord` identity
fields plus versioning.

## Schema

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `plan_id` | `str` | ✅ | — | Unique identifier for this plan |
| `subgoal_id` | `str` | ✅ | — | Primary subgoal this plan addresses |
| `segments` | `List[str]` | ✅ | — | Ordered list of segment IDs |
| `intent` | `str` | ✅ | — | Goal description ("what to do") |
| `targetskillid` | `str` | ✅ | — | Primary skill to invoke |
| `arguments` | `Dict[str, Any]` | ✅ | `{}` (factory) | Skill invocation arguments |
| `reasoning_summary` | `str` | ✅ | — | Why this plan was chosen |
| `created_at` | `str` | ✅ | — | ISO 8601 timestamp |
| `metadata` | `Dict[str, Any]` | ❌ | `{}` | Arbitrary metadata |
| `subgoals` | `List[str]` | ❌ | `[subgoal_id]` | All subgoals covered by this plan |
| `version` | `str` | ❌ | `"1.0"` | Contract version identifier |
| `status` | `PlanStatus` | ❌ | `PENDING` | Runtime state (not frozen) |

## Validation Rules

1. `plan_id`, `subgoal_id`, `intent`, `targetskillid`, `created_at`,
   `version` must be non-empty strings.
2. `subgoals` defaults to `[subgoal_id]` if empty; `subgoal_id` is
   prepended if missing from the list.
3. `version` is automatically set to `CURRENT_CONTRACT_VERSION` on
   construction.

## Serialization

- `to_dict()` → JSON-compatible dict (round-trip safe via `from_dict()`)
- `from_plan_and_record()` → migration path from pre-v1.0 types
- `status` field is serialized via `PlanStatus.value` (string enum)

## Cross-Stratum Usage

- **S2→S1:** Plan passed to executor via `AgentPlan.targetskillid` and
  `arguments`.
- **S2→S3:** Plan forwarded for capability discovery and invocation.
- **S2 internal:** Plans stored in `PlanMemory` with identity from
  `plan_id` + `subgoal_id`.
