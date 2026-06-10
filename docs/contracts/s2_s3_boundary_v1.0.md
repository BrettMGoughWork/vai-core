# S2↔S3 Execution Contract v1.0

**Source:** `src/capabilities/contracts.py`
**Version constant:** `S2_S3_CONTRACT_VERSION = "1.0"`

## Purpose

Defines the only shapes allowed to cross the S2↔S3 boundary for skill
invocation and discovery. All types are pure frozen dataclasses,
JSON-serializable, with no runtime logic. No imports from S1, S2, or
S3 internals.

## Types

### `SkillCallRequest`

Request from S2 to S3 to execute a skill.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `skill_name` | `str` | ✅ | — | Name of the skill to invoke |
| `arguments` | `Dict[str, Any]` | ❌ | `{}` | Skill arguments |
| `request_id` | `str` | ❌ (validated) | `""` | Unique request identifier |
| `context` | `Dict[str, Any]` | ❌ (validated) | `{}` | Execution context |
| `contract_version` | `str` | ❌ | `"1.0"` | Contract version |

**Validation:** `skill_name` and `request_id` must be non-empty.
`arguments` and `context` must be dicts.

### `SkillResult`

Response from S3 to S2 after skill execution.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `request_id` | `str` | ✅ | — | Correlates to `SkillCallRequest.request_id` |
| `success` | `bool` | ✅ | — | Whether execution succeeded |
| `output` | `Dict[str, Any] \| None` | ❌ | `None` | Result data (set iff success) |
| `error` | `str \| None` | ❌ | `None` | Error message (set iff failure) |
| `contract_version` | `str` | ❌ | `"1.0"` | Contract version |

**Validation:** Exactly one of `output` or `error` must be non-None.
`request_id` must be non-empty.

### `SkillDiscoveryQuery`

Request from S2 to S3 to discover available skills.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | `str` | ✅ | — | Search query string |
| `limit` | `int` | ❌ | `10` | Maximum results to return |

**Validation:** `query` must be non-empty, `limit >= 1`.

### `DiscoveredSkill`

Summary of a skill returned by discovery.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | `str` | ✅ | — | Skill name |
| `description` | `str` | ✅ | — | Skill description |
| `score` | `float` | ❌ | `0.0` | Relevance score `[0.0, 1.0]` |
| `input_schema` | `dict[str, Any] \| None` | ❌ | `None` | Parameter schema |
| `output_schema` | `dict[str, Any] \| None` | ❌ | `None` | Output schema |

### `SkillDiscoveryResult`

Response from S3 to S2 with discovered skills.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | `SkillDiscoveryQuery` | ✅ | — | Original query |
| `skills` | `List[DiscoveredSkill]` | ❌ | `[]` | Results, sorted by descending score |

**Validation:** Skills must be sorted by descending score, and count
must not exceed `query.limit`.

## Cross-Stratum Flow

```
S2 (Planner)                     S3 (Runtime)
    │                                │
    ├── SkillCallRequest ──────────► │ execute skill
    │ ◄───────── SkillResult ────────┤
    │                                │
    ├── SkillDiscoveryQuery ───────► │ find capabilities
    │ ◄── SkillDiscoveryResult ──────┤
```

## Version Stability

This contract is frozen at v1.0 for Release 0.1. The S2↔S3 adapter in
S2's runtime is the sole integration point and must not import S1/S2/S3
internals beyond these contract types.
