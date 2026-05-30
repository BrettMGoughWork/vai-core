# Architecture Audit Report

> **architecture.json snapshot**: `2026-05-30 06:54:27 UTC`  
> **Audit generated**: `2026-05-30 06:54:27 UTC`  
> **Classes analysed**: 209 | **References**: 617

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟠 High     | 0 |
| 🟡 Medium   | 32 |
| 🔵 Low      | 18 |
| **Total**   | **50** |

---

## 1. Duplicate Classes (6 found)

### 🔵 Duplicate class name: `FakeMetadata`

**Severity**: `low`  
**Category**: `duplicate`  
**fan_in**: 1 | **fan_out**: 0

Defined in 2 files: `tests/unit/test_skill_filter.py`, `tests/unit/test_skill_ranker.py`

### 🔵 Duplicate class name: `FakeRuntimeState`

**Severity**: `low`  
**Category**: `duplicate`  
**fan_in**: 0 | **fan_out**: 0

Defined in 2 files: `tests/unit/test_core_signals_emitters.py`, `tests/unit/test_core_signals_interface.py`

### 🔵 Duplicate class name: `FakeSegmentState`

**Severity**: `low`  
**Category**: `duplicate`  
**fan_in**: 0 | **fan_out**: 0

Defined in 2 files: `tests/unit/test_core_signals_emitters.py`, `tests/unit/test_core_signals_interface.py`

### 🔵 Duplicate class name: `FakeSkill`

**Severity**: `low`  
**Category**: `duplicate`  
**fan_in**: 0 | **fan_out**: 1

Defined in 4 files: `tests/unit/test_local_planner.py`, `tests/unit/test_singleskillexecutor.py`, `tests/unit/test_skill_filter.py`, `tests/unit/test_skill_ranker.py`

### 🔵 Duplicate class name: `FakeSubgoal`

**Severity**: `low`  
**Category**: `duplicate`  
**fan_in**: 0 | **fan_out**: 0

Defined in 2 files: `tests/unit/test_core_signals_emitters.py`, `tests/unit/test_core_signals_interface.py`

### 🔵 Duplicate class name: `FakeSubgoalState`

**Severity**: `low`  
**Category**: `duplicate`  
**fan_in**: 0 | **fan_out**: 0

Defined in 2 files: `tests/unit/test_core_signals_emitters.py`, `tests/unit/test_core_signals_interface.py`

---

## 2. Architecture Violations (cross-stratum imports) (0 found)

_No issues found._

---

## 3. Stratum Invariant Violations (13 found)

### 🟡 I5 — Utility class `StepProcessor` has excessive fan_out (18)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 5 | **fan_out**: 18

`StepProcessor` in `src/core/planning/step_processor.py` references 18 other types. Suggests violation of single responsibility.

### 🟡 I3 — Utility class `LocalPlanner` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 1 | **fan_out**: 3

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
**fan_in**: 5 | **fan_out**: 0

`ToolPromptBuilder` in `src/tools/prompt_builder.py`. Test code must live under `tests/`, not `src/`.

### 🟡 I6 — Test class `ToolSchemaGenerator` is inside `src/`

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 5 | **fan_out**: 0

`ToolSchemaGenerator` in `src/tools/schema.py`. Test code must live under `tests/`, not `src/`.

### 🟡 I6 — Test class `ToolValidator` is inside `src/`

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 5 | **fan_out**: 1

`ToolValidator` in `src/tools/validator.py`. Test code must live under `tests/`, not `src/`.

---

## 4. Dead Code (fan_in = 0) (31 found)

### 🟡 Unreferenced class: `AgentLoop` (adapter)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 11

`AgentLoop` in `src/agent/loop.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `Config` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 0

`Config` in `src/core/config/loader.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `CoreConfig` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 6

`CoreConfig` in `src/core/config/model.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

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
**fan_in**: 0 | **fan_out**: 2

`MinimalCoreStepExecutor` in `src/execution/minimal_executor.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

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

### 🟡 Unreferenced class: `Telemetry` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 1

`Telemetry` in `src/telemetry/telemetry.py` has fan_in=0 — no other class imports or references it. Has 3 public methods.

---

## 5. Priority-Ranked Issues

| # | Sev | Category | Title |
|---|-----|----------|-------|
| 1 | 🟡 `medium` | `invariant` | I5 — Utility class `StepProcessor` has excessive fan_out (18) |
| 2 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanValidator` has reasoning keyword `plan` in name |
| 3 | 🟡 `medium` | `invariant` | I6 — Test class `ToolValidator` is inside `src/` |
| 4 | 🟡 `medium` | `invariant` | I6 — Test class `ToolPromptBuilder` is inside `src/` |
| 5 | 🟡 `medium` | `invariant` | I6 — Test class `ToolSchemaGenerator` is inside `src/` |
| 6 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanGenerator` has reasoning keyword `plan` in name |
| 7 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanPrompt` has reasoning keyword `plan` in name |
| 8 | 🟡 `medium` | `invariant` | I3 — Utility class `LocalPlanner` has reasoning keyword `plan` in name |
| 9 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanSegmentValidator` has reasoning keyword `plan` in name |
| 10 | 🟡 `medium` | `invariant` | I5 — Utility class `SubgoalManager` has excessive fan_out (14) |
| 11 | 🟡 `medium` | `dead-code` | Unreferenced class: `SubgoalManager` (utility) |
| 12 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanSegmentManager` has reasoning keyword `plan` in name |
| 13 | 🟡 `medium` | `dead-code` | Unreferenced class: `AgentLoop` (adapter) |
| 14 | 🟡 `medium` | `dead-code` | Unreferenced class: `PlanSegmentManager` (utility) |
| 15 | 🟡 `medium` | `dead-code` | Unreferenced class: `BaseSkill` (domain) |
| 16 | 🟡 `medium` | `dead-code` | Unreferenced class: `CoreConfig` (utility) |
| 17 | 🟡 `medium` | `dead-code` | Unreferenced class: `PlanTransitionPolicy` (infrastructure) |
| 18 | 🟡 `medium` | `dead-code` | Unreferenced class: `EnforcedLoopPolicy` (infrastructure) |
| 19 | 🟡 `medium` | `dead-code` | Unreferenced class: `Executor` (infrastructure) |
| 20 | 🟡 `medium` | `dead-code` | Unreferenced class: `ForbiddenCapabilityPolicy` (infrastructure) |
| 21 | 🟡 `medium` | `dead-code` | Unreferenced class: `StructuredLogger` (infrastructure) |
| 22 | 🟡 `medium` | `dead-code` | Unreferenced class: `CapabilityRegistry` (utility) |
| 23 | 🟡 `medium` | `dead-code` | Unreferenced class: `Governance` (infrastructure) |
| 24 | 🟡 `medium` | `dead-code` | Unreferenced class: `MinimalCoreStepExecutor` (infrastructure) |
| 25 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanStateValidationError` has reasoning keyword `plan` in name |
| 26 | 🟡 `medium` | `dead-code` | Unreferenced class: `LoopTerminationDecision` (utility) |
| 27 | 🟡 `medium` | `dead-code` | Unreferenced class: `Telemetry` (infrastructure) |
| 28 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanValidationResult` has reasoning keyword `plan` in name |
| 29 | 🟡 `medium` | `dead-code` | Unreferenced class: `Config` (utility) |
| 30 | 🟡 `medium` | `dead-code` | Unreferenced class: `DeadCodeIgnore` (domain) |
| 31 | 🟡 `medium` | `dead-code` | Unreferenced class: `MinimalSafetyPolicy` (infrastructure) |
| 32 | 🟡 `medium` | `dead-code` | Unreferenced class: `PlanValidationResult` (utility) |
| 33 | 🔵 `low` | `duplicate` | Duplicate class name: `FakeMetadata` |
| 34 | 🔵 `low` | `dead-code` | Unreferenced class: `RecoveryAction` (domain) |
| 35 | 🔵 `low` | `dead-code` | Unreferenced class: `GovernanceError` (domain) |
| 36 | 🔵 `low` | `dead-code` | Unreferenced class: `ExecutionError` (domain) |
| 37 | 🔵 `low` | `dead-code` | Unreferenced class: `MappingError` (domain) |
| 38 | 🔵 `low` | `dead-code` | Unreferenced class: `PlanningError` (domain) |
| 39 | 🔵 `low` | `dead-code` | Unreferenced class: `SemanticError` (domain) |
| 40 | 🔵 `low` | `dead-code` | Unreferenced class: `StateError` (domain) |
| 41 | 🔵 `low` | `duplicate` | Duplicate class name: `FakeSkill` |
| 42 | 🔵 `low` | `dead-code` | Unreferenced class: `LLMError` (domain) |
| 43 | 🔵 `low` | `dead-code` | Unreferenced class: `PlanStateValidationError` (utility) |
| 44 | 🔵 `low` | `dead-code` | Unreferenced class: `SemanticValidationError` (domain) |
| 45 | 🔵 `low` | `dead-code` | Unreferenced class: `SystemError` (domain) |
| 46 | 🔵 `low` | `dead-code` | Unreferenced class: `ToolExecutionError` (infrastructure) |
| 47 | 🔵 `low` | `duplicate` | Duplicate class name: `FakeRuntimeState` |
| 48 | 🔵 `low` | `duplicate` | Duplicate class name: `FakeSegmentState` |
| 49 | 🔵 `low` | `duplicate` | Duplicate class name: `FakeSubgoalState` |
| 50 | 🔵 `low` | `duplicate` | Duplicate class name: `FakeSubgoal` |
