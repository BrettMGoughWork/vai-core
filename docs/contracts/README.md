# Release 0.1 Frozen Contracts

All S2 contracts are locked at **v1.0** as of Phase 2.18.2. Any change
to these schemas requires a contract version bump and a Release 0.1
exception review.

| Contract | Source | Version |
|----------|--------|---------|
| [AgentPlan](agent_plan_v1.0.md) | `src/core/planning/contracts/agent_plan.py` | 1.0 |
| [StepSpec](step_spec_v1.0.md) | `src/core/planning/contracts/step_spec.py` | 1.0 |
| [S2↔S3 Boundary](s2_s3_boundary_v1.0.md) | `src/capabilities/contracts.py` | 1.0 |

## Freeze Date

Phase 2.18.2 — Frozen for Release 0.1 ("Hierarchical Reasoner")

## Contract Change Policy

1. Any breaking change to a v1.0 contract requires bumping the version
   constant, updating the corresponding `docs/contracts/` document, and
   an exception review.
2. Additive-only changes (new optional fields with defaults) may be
   considered backward-compatible.
3. All contract tests must pass before and after any change.
