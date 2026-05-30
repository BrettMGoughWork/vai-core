# Architecture Audit Report

> **architecture.json snapshot**: `2026-05-30 07:10:03 UTC`  
> **Audit generated**: `2026-05-30 07:10:25 UTC`  
> **Classes analysed**: 174 | **References**: 538

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟠 High     | 5 |
| 🟡 Medium   | 39 |
| 🔵 Low      | 12 |
| **Total**   | **56** |

---

## 1. Duplicate Classes (3 found)

### 🟠 Duplicate class name: `AgentConfig`

**Severity**: `high`  
**Category**: `duplicate`  
**fan_in**: 12 | **fan_out**: 6

Defined in 2 files: `src/core/config/model.py`, `src/core/state/config.py`

### 🟠 Duplicate class name: `ExecutionResult`

**Severity**: `high`  
**Category**: `duplicate`  
**fan_in**: 3 | **fan_out**: 1

Defined in 2 files: `src/execution/executor.py`, `src/execution/executor_contract.py`

### 🟠 Duplicate class name: `LoopPolicyConfig`

**Severity**: `high`  
**Category**: `duplicate`  
**fan_in**: 3 | **fan_out**: 1

Defined in 2 files: `src/core/config/model.py`, `src/core/state/config.py`

---

## 2. Architecture Violations (cross-stratum imports) (1 found)

### 🟠 Forbidden import: `SafeStepDispatcher` (infrastructure) → `AgentDispatcher` (adapter)

**Severity**: `high`  
**Category**: `arch-violation`  
**fan_in**: 0 | **fan_out**: 0

`SafeStepDispatcher` (stratum: **infrastructure**) imports from `AgentDispatcher` (stratum: **adapter**). Allowed strata for infrastructure: ['domain', 'infrastructure', 'utility'].

---

## 3. Stratum Invariant Violations (14 found)

### 🟡 I5 — Utility class `StepProcessor` has excessive fan_out (18)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 5 | **fan_out**: 18

`StepProcessor` in `src/core/planning/step_processor.py` references 18 other types. Suggests violation of single responsibility.

### 🟠 I2 — Infrastructure class `SafeStepDispatcher` imports adapter: `dispatcher`

**Severity**: `high`  
**Category**: `invariant`  
**fan_in**: 3 | **fan_out**: 2

`SafeStepDispatcher` in `src/core/planning/dispatch/safe_step_dispatcher.py`. Infrastructure must not depend on adapters.

### 🟡 I3 — Utility class `LocalPlanner` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 0 | **fan_out**: 3

`LocalPlanner` in `src/core/planning/generator/local_planner.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I3 — Utility class `PlanPrompt` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 3 | **fan_out**: 2

`PlanPrompt` in `src/core/planning/generator/plan_generator.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I3 — Utility class `PlanGenerator` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 4 | **fan_out**: 4

`PlanGenerator` in `src/core/planning/generator/plan_generator.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I3 — Utility class `PlanSegmentManager` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 0 | **fan_out**: 11

`PlanSegmentManager` in `src/core/planning/segments/manager.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I5 — Utility class `SubgoalManager` has excessive fan_out (14)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 0 | **fan_out**: 14

`SubgoalManager` in `src/core/planning/subgoals/manager.py` references 14 other types. Suggests violation of single responsibility.

### 🟡 I3 — Utility class `PlanSegmentValidator` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 1 | **fan_out**: 3

`PlanSegmentValidator` in `src/core/planning/validators/plan_segment_validator.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I3 — Utility class `PlanStateValidationError` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 0 | **fan_out**: 1

`PlanStateValidationError` in `src/core/planning/validators/plan_state_validators.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I3 — Utility class `PlanValidationResult` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 0 | **fan_out**: 0

`PlanValidationResult` in `src/core/planning/validators/plan_validation.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I3 — Utility class `PlanValidator` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 5 | **fan_out**: 9

`PlanValidator` in `src/core/planning/validators/plan_validator.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I6 — Test class `ToolPromptBuilder` is inside `src/`

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 0 | **fan_out**: 0

`ToolPromptBuilder` in `src/core/tools/prompt_builder.py`. Test code must live under `tests/`, not `src/`.

### 🟡 I6 — Test class `ToolSchemaGenerator` is inside `src/`

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 0 | **fan_out**: 0

`ToolSchemaGenerator` in `src/core/tools/schema.py`. Test code must live under `tests/`, not `src/`.

### 🟡 I6 — Test class `ToolValidator` is inside `src/`

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 0 | **fan_out**: 1

`ToolValidator` in `src/core/tools/validator.py`. Test code must live under `tests/`, not `src/`.

---

## 4. Dead Code (fan_in = 0) (38 found)

### 🟡 Unreferenced class: `Config` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 5

`Config` in `src/core/config/loader.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `LLMTransport` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 5

`LLMTransport` in `src/core/llm/transport.py` has fan_in=0 — no other class imports or references it. Has 2 public methods.

### 🟡 Unreferenced class: `LocalPlanner` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 3

`LocalPlanner` in `src/core/planning/generator/local_planner.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `LoopTerminationDecision` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 1

`LoopTerminationDecision` in `src/core/planning/orchestration/loop_termination.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🟡 Unreferenced class: `MinimalSafetyPolicy` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 0

`MinimalSafetyPolicy` in `src/core/planning/safety/minimal_policy.py` has fan_in=0 — no other class imports or references it. Has 2 public methods.

### 🟡 Unreferenced class: `Policy` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 4

`Policy` in `src/core/planning/safety/policy.py` has fan_in=0 — no other class imports or references it. Has 4 public methods.

### 🟡 Unreferenced class: `EnforcedLoopPolicy` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 4

`EnforcedLoopPolicy` in `src/core/planning/safety/policy_adapter.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `ForbiddenCapabilityPolicy` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 3

`ForbiddenCapabilityPolicy` in `src/core/planning/safety/safety_policies.py` has fan_in=0 — no other class imports or references it. Has 2 public methods.

### 🟡 Unreferenced class: `PlanTransitionPolicy` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 6

`PlanTransitionPolicy` in `src/core/planning/safety/safety_policies.py` has fan_in=0 — no other class imports or references it. Has 2 public methods.

### 🟡 Unreferenced class: `PlanSegmentManager` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 11

`PlanSegmentManager` in `src/core/planning/segments/manager.py` has fan_in=0 — no other class imports or references it. Has 3 public methods.

### 🟡 Unreferenced class: `SubgoalManager` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 14

`SubgoalManager` in `src/core/planning/subgoals/manager.py` has fan_in=0 — no other class imports or references it. Has 6 public methods.

### 🔵 Unreferenced class: `PlanStateValidationError` (utility)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 1

`PlanStateValidationError` in `src/core/planning/validators/plan_state_validators.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🟡 Unreferenced class: `PlanValidationResult` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 0

`PlanValidationResult` in `src/core/planning/validators/plan_validation.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🟡 Unreferenced class: `CapabilityRegistry` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 2

`CapabilityRegistry` in `src/core/planning/validators/plan_validation.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `CoreStepExecutor` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 16

`CoreStepExecutor` in `src/core/state/core_step_executor.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `AgentRuntime` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 14

`AgentRuntime` in `src/core/state/runtime.py` has fan_in=0 — no other class imports or references it. Has 2 public methods.

### 🔵 Unreferenced class: `PlanningError` (domain)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 2

`PlanningError` in `src/core/types/errors/AgentError.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🔵 Unreferenced class: `MappingError` (domain)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 2

`MappingError` in `src/core/types/errors/AgentError.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🔵 Unreferenced class: `ExecutionError` (domain)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 2

`ExecutionError` in `src/core/types/errors/AgentError.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🔵 Unreferenced class: `StateError` (domain)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 2

`StateError` in `src/core/types/errors/AgentError.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🔵 Unreferenced class: `GovernanceError` (domain)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 3

`GovernanceError` in `src/core/types/errors/AgentError.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🔵 Unreferenced class: `SemanticError` (domain)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 2

`SemanticError` in `src/core/types/errors/AgentError.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🔵 Unreferenced class: `LLMError` (domain)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 1

`LLMError` in `src/core/types/errors/LLMError.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🔵 Unreferenced class: `SystemError` (domain)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 1

`SystemError` in `src/core/types/errors/SystemError.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🔵 Unreferenced class: `RecoveryAction` (domain)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 6

`RecoveryAction` in `src/core/types/errors/recovery.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🟡 Unreferenced class: `DeadCodeIgnore` (domain)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 0

`DeadCodeIgnore` in `src/core/types/validation/deadcode_markers.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🔵 Unreferenced class: `ToolExecutionError` (infrastructure)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 1

`ToolExecutionError` in `src/execution/errors.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🟡 Unreferenced class: `Executor` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 3

`Executor` in `src/execution/executor.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `MinimalCoreStepExecutor` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 8

`MinimalCoreStepExecutor` in `src/execution/minimal_executor.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `SingleSkillExecutor` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 9

`SingleSkillExecutor` in `src/execution/singleskillexecutor.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `RetryPolicy` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 3

`RetryPolicy` in `src/execution/retry/retry_policy.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `Governance` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 2

`Governance` in `src/governance/schema.py` has fan_in=0 — no other class imports or references it. Has 2 public methods.

### 🟡 Unreferenced class: `StructuredLogger` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 3

`StructuredLogger` in `src/observability/logger.py` has fan_in=0 — no other class imports or references it. Has 5 public methods.

### 🟡 Unreferenced class: `BaseSkill` (domain)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 10

`BaseSkill` in `src/primitives/base.py` has fan_in=0 — no other class imports or references it. Has 2 public methods.

### 🔵 Unreferenced class: `SemanticValidationError` (domain)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 1

`SemanticValidationError` in `src/primitives/runtime/semantic.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

### 🟡 Unreferenced class: `SkillFilter` (domain)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 1

`SkillFilter` in `src/primitives/runtime/skill_filter.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `SkillRanker` (domain)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 1

`SkillRanker` in `src/primitives/runtime/skill_ranker.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `Telemetry` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 1

`Telemetry` in `src/telemetry/telemetry.py` has fan_in=0 — no other class imports or references it. Has 3 public methods.

---

## 5. Priority-Ranked Issues

| # | Sev | Category | Title |
|---|-----|----------|-------|
| 1 | 🟠 `high` | `duplicate` | Duplicate class name: `AgentConfig` |
| 2 | 🟠 `high` | `invariant` | I2 — Infrastructure class `SafeStepDispatcher` imports adapter: `dispatcher` |
| 3 | 🟠 `high` | `duplicate` | Duplicate class name: `ExecutionResult` |
| 4 | 🟠 `high` | `duplicate` | Duplicate class name: `LoopPolicyConfig` |
| 5 | 🟠 `high` | `arch-violation` | Forbidden import: `SafeStepDispatcher` (infrastructure) → `AgentDispatcher` (adapter) |
| 6 | 🟡 `medium` | `invariant` | I5 — Utility class `StepProcessor` has excessive fan_out (18) |
| 7 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanValidator` has reasoning keyword `plan` in name |
| 8 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanGenerator` has reasoning keyword `plan` in name |
| 9 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanPrompt` has reasoning keyword `plan` in name |
| 10 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanSegmentValidator` has reasoning keyword `plan` in name |
| 11 | 🟡 `medium` | `dead-code` | Unreferenced class: `CoreStepExecutor` (infrastructure) |
| 12 | 🟡 `medium` | `invariant` | I5 — Utility class `SubgoalManager` has excessive fan_out (14) |
| 13 | 🟡 `medium` | `dead-code` | Unreferenced class: `AgentRuntime` (infrastructure) |
| 14 | 🟡 `medium` | `dead-code` | Unreferenced class: `SubgoalManager` (utility) |
| 15 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanSegmentManager` has reasoning keyword `plan` in name |
| 16 | 🟡 `medium` | `dead-code` | Unreferenced class: `PlanSegmentManager` (utility) |
| 17 | 🟡 `medium` | `dead-code` | Unreferenced class: `BaseSkill` (domain) |
| 18 | 🟡 `medium` | `dead-code` | Unreferenced class: `SingleSkillExecutor` (infrastructure) |
| 19 | 🟡 `medium` | `dead-code` | Unreferenced class: `MinimalCoreStepExecutor` (infrastructure) |
| 20 | 🟡 `medium` | `dead-code` | Unreferenced class: `PlanTransitionPolicy` (infrastructure) |
| 21 | 🟡 `medium` | `dead-code` | Unreferenced class: `Config` (utility) |
| 22 | 🟡 `medium` | `dead-code` | Unreferenced class: `LLMTransport` (infrastructure) |
| 23 | 🟡 `medium` | `dead-code` | Unreferenced class: `EnforcedLoopPolicy` (infrastructure) |
| 24 | 🟡 `medium` | `dead-code` | Unreferenced class: `Policy` (infrastructure) |
| 25 | 🟡 `medium` | `invariant` | I3 — Utility class `LocalPlanner` has reasoning keyword `plan` in name |
| 26 | 🟡 `medium` | `dead-code` | Unreferenced class: `Executor` (infrastructure) |
| 27 | 🟡 `medium` | `dead-code` | Unreferenced class: `ForbiddenCapabilityPolicy` (infrastructure) |
| 28 | 🟡 `medium` | `dead-code` | Unreferenced class: `LocalPlanner` (utility) |
| 29 | 🟡 `medium` | `dead-code` | Unreferenced class: `RetryPolicy` (infrastructure) |
| 30 | 🟡 `medium` | `dead-code` | Unreferenced class: `StructuredLogger` (infrastructure) |
| 31 | 🟡 `medium` | `dead-code` | Unreferenced class: `CapabilityRegistry` (utility) |
| 32 | 🟡 `medium` | `dead-code` | Unreferenced class: `Governance` (infrastructure) |
| 33 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanStateValidationError` has reasoning keyword `plan` in name |
| 34 | 🟡 `medium` | `invariant` | I6 — Test class `ToolValidator` is inside `src/` |
| 35 | 🟡 `medium` | `dead-code` | Unreferenced class: `LoopTerminationDecision` (utility) |
| 36 | 🟡 `medium` | `dead-code` | Unreferenced class: `SkillFilter` (domain) |
| 37 | 🟡 `medium` | `dead-code` | Unreferenced class: `SkillRanker` (domain) |
| 38 | 🟡 `medium` | `dead-code` | Unreferenced class: `Telemetry` (infrastructure) |
| 39 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanValidationResult` has reasoning keyword `plan` in name |
| 40 | 🟡 `medium` | `invariant` | I6 — Test class `ToolPromptBuilder` is inside `src/` |
| 41 | 🟡 `medium` | `invariant` | I6 — Test class `ToolSchemaGenerator` is inside `src/` |
| 42 | 🟡 `medium` | `dead-code` | Unreferenced class: `DeadCodeIgnore` (domain) |
| 43 | 🟡 `medium` | `dead-code` | Unreferenced class: `MinimalSafetyPolicy` (infrastructure) |
| 44 | 🟡 `medium` | `dead-code` | Unreferenced class: `PlanValidationResult` (utility) |
| 45 | 🔵 `low` | `dead-code` | Unreferenced class: `RecoveryAction` (domain) |
| 46 | 🔵 `low` | `dead-code` | Unreferenced class: `GovernanceError` (domain) |
| 47 | 🔵 `low` | `dead-code` | Unreferenced class: `ExecutionError` (domain) |
| 48 | 🔵 `low` | `dead-code` | Unreferenced class: `MappingError` (domain) |
| 49 | 🔵 `low` | `dead-code` | Unreferenced class: `PlanningError` (domain) |
| 50 | 🔵 `low` | `dead-code` | Unreferenced class: `SemanticError` (domain) |
| 51 | 🔵 `low` | `dead-code` | Unreferenced class: `StateError` (domain) |
| 52 | 🔵 `low` | `dead-code` | Unreferenced class: `LLMError` (domain) |
| 53 | 🔵 `low` | `dead-code` | Unreferenced class: `PlanStateValidationError` (utility) |
| 54 | 🔵 `low` | `dead-code` | Unreferenced class: `SemanticValidationError` (domain) |
| 55 | 🔵 `low` | `dead-code` | Unreferenced class: `SystemError` (domain) |
| 56 | 🔵 `low` | `dead-code` | Unreferenced class: `ToolExecutionError` (infrastructure) |
