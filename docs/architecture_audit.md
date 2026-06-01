# Architecture Audit Report

> **architecture.json snapshot**: `2026-06-01 09:15:03 UTC`  
> **Audit generated**: `2026-06-01 09:15:03 UTC`  
> **Classes analysed**: 238 | **References**: 1049

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟠 High     | 0 |
| 🟡 Medium   | 69 |
| 🔵 Low      | 13 |
| **Total**   | **82** |

---

## 1. Duplicate Classes (1 found)

### 🟡 Near-duplicate classes: `SegmentMemory` ↔ `SubgoalMemory` (similarity 90%)

**Severity**: `medium`  
**Category**: `near-duplicate`  
**fan_in**: 23 | **fan_out**: 7

`SegmentMemory` in `src/core/memory/segment_memory.py` (utility), `SubgoalMemory` in `src/core/memory/subgoal_memory.py` (utility). Shared methods: ['exists', 'get', 'get_chain', 'get_children', 'get_record', 'list_all', 'load_snapshot', 'put', 'snapshot']

---

## 2. Architecture Violations (cross-stratum imports) (0 found)

_No issues found._

---

## 3. Stratum Invariant Violations (33 found)

### 🟡 I3 — Utility class `PlanMemory` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 23 | **fan_out**: 7

`PlanMemory` in `src/core/memory/plan_memory.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I3 — Utility class `PlanMemoryRecord` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 37 | **fan_out**: 3

`PlanMemoryRecord` in `src/core/memory/plan_memory_types.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I3 — Utility class `PlanMemorySnapshot` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 2 | **fan_out**: 2

`PlanMemorySnapshot` in `src/core/memory/plan_memory_types.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I5 — Utility class `EvictionRules` has excessive fan_out (14)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 0 | **fan_out**: 14

`EvictionRules` in `src/core/memory/eviction/eviction_rules.py` references 14 other types. Suggests violation of single responsibility.

### 🟡 I3 — Utility class `PlanRepair` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 2 | **fan_out**: 21

`PlanRepair` in `src/core/memory/repair/plan_repair.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I5 — Utility class `PlanRepair` has excessive fan_out (21)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 2 | **fan_out**: 21

`PlanRepair` in `src/core/memory/repair/plan_repair.py` references 21 other types. Suggests violation of single responsibility.

### 🟡 I3 — Utility class `PlanBreakageReport` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 2 | **fan_out**: 7

`PlanBreakageReport` in `src/core/memory/repair/repair_types.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I3 — Utility class `RepairPlan` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 2 | **fan_out**: 2

`RepairPlan` in `src/core/memory/repair/repair_types.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I5 — Utility class `SummarisationRules` has excessive fan_out (13)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 1 | **fan_out**: 13

`SummarisationRules` in `src/core/memory/summarisation/summarisation_rules.py` references 13 other types. Suggests violation of single responsibility.

### 🟡 I3 — Utility class `PlanSummary` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 2 | **fan_out**: 1

`PlanSummary` in `src/core/memory/summarisation/summary_types.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I5 — Utility class `StepProcessor` has excessive fan_out (18)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 3 | **fan_out**: 18

`StepProcessor` in `src/core/planning/step_processor.py` references 18 other types. Suggests violation of single responsibility.

### 🟡 I3 — Utility class `TerminationReason` has reasoning keyword `reason` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 3 | **fan_out**: 6

`TerminationReason` in `src/core/planning/agent_loop/agent_loop_types.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I5 — Utility class `AgentState` has excessive fan_out (13)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 2 | **fan_out**: 13

`AgentState` in `src/core/planning/agent_loop/agent_loop_types.py` references 13 other types. Suggests violation of single responsibility.

### 🟡 I5 — Utility class `AgentLoopV2` has excessive fan_out (34)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 0 | **fan_out**: 34

`AgentLoopV2` in `src/core/planning/agent_loop/agent_loop_v2.py` references 34 other types. Suggests violation of single responsibility.

### 🟡 I5 — Utility class `DriftDetector` has excessive fan_out (18)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 0 | **fan_out**: 18

`DriftDetector` in `src/core/planning/drift/drift_detector.py` references 18 other types. Suggests violation of single responsibility.

### 🟡 I5 — Utility class `FullDriftDetector` has excessive fan_out (18)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 2 | **fan_out**: 18

`FullDriftDetector` in `src/core/planning/drift/full_drift_detector.py` references 18 other types. Suggests violation of single responsibility.

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
**fan_in**: 2 | **fan_out**: 4

`PlanGenerator` in `src/core/planning/generator/plan_generator.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I3 — Utility class `SubgoalPlanner` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 2 | **fan_out**: 7

`SubgoalPlanner` in `src/core/planning/generator/subgoal_planner.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

### 🟡 I5 — Utility class `ReflectionLoop` has excessive fan_out (33)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 2 | **fan_out**: 33

`ReflectionLoop` in `src/core/planning/reflection/reflection_loop.py` references 33 other types. Suggests violation of single responsibility.

### 🟡 I3 — Utility class `PlanAdjustment` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 3 | **fan_out**: 2

`PlanAdjustment` in `src/core/planning/reflection/reflection_types.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

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

### 🟡 I5 — Utility class `FullValidationEngine` has excessive fan_out (28)

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 4 | **fan_out**: 28

`FullValidationEngine` in `src/core/planning/validation/full_validation_engine.py` references 28 other types. Suggests violation of single responsibility.

### 🟡 I3 — Utility class `PlanRecordValidationResult` has reasoning keyword `plan` in name

**Severity**: `medium`  
**Category**: `invariant`  
**fan_in**: 3 | **fan_out**: 3

`PlanRecordValidationResult` in `src/core/planning/validation/validation_types.py`. Stratum 1 must be reactive and deterministic. Reasoning/planning logic belongs in Stratum 2 (domain).

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
**fan_in**: 2 | **fan_out**: 9

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

## 4. Dead Code (fan_in = 0) (48 found)

### 🟡 Unreferenced class: `AgentDispatcher` (adapter)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 0

`AgentDispatcher` in `src/agent/dispatcher.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `Config` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 5

`Config` in `src/core/config/loader.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `MockLLM` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 5

`MockLLM` in `src/core/llm/mock_llm.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `LLMTransport` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 5

`LLMTransport` in `src/core/llm/transport.py` has fan_in=0 — no other class imports or references it. Has 2 public methods.

### 🟡 Unreferenced class: `EvictionRules` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 14

`EvictionRules` in `src/core/memory/eviction/eviction_rules.py` has fan_in=0 — no other class imports or references it. Has 7 public methods.

### 🟡 Unreferenced class: `AgentLoopV2` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 34

`AgentLoopV2` in `src/core/planning/agent_loop/agent_loop_v2.py` has fan_in=0 — no other class imports or references it. Has 2 public methods.

### 🟡 Unreferenced class: `PlanExecutor` (infrastructure)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 17

`PlanExecutor` in `src/core/planning/dispatch/plan_executor.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `DriftDetector` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 18

`DriftDetector` in `src/core/planning/drift/drift_detector.py` has fan_in=0 — no other class imports or references it. Has 3 public methods.

### 🟡 Unreferenced class: `LocalPlanner` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 3

`LocalPlanner` in `src/core/planning/generator/local_planner.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

### 🟡 Unreferenced class: `LoopOrchestrator` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 7

`LoopOrchestrator` in `src/core/planning/orchestration/loop_orchestrator.py` has fan_in=0 — no other class imports or references it. Has 1 public methods.

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

### 🟡 Unreferenced class: `TransitionEngine` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 4

`TransitionEngine` in `src/core/planning/subgoals/transition_engine.py` has fan_in=0 — no other class imports or references it. Has 3 public methods.

### 🟡 Unreferenced class: `ValidationEngine` (utility)

**Severity**: `medium`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 3

`ValidationEngine` in `src/core/planning/subgoals/validation_engine.py` has fan_in=0 — no other class imports or references it. Has 2 public methods.

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

### 🔵 Unreferenced class: `SignalSource` (domain)

**Severity**: `low`  
**Category**: `dead-code`  
**fan_in**: 0 | **fan_out**: 7

`SignalSource` in `src/core/signals/model.py` has fan_in=0 — no other class imports or references it. No public methods (possible stub).

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
| 1 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanMemoryRecord` has reasoning keyword `plan` in name |
| 2 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanMemory` has reasoning keyword `plan` in name |
| 3 | 🟡 `medium` | `near-duplicate` | Near-duplicate classes: `SegmentMemory` ↔ `SubgoalMemory` (similarity 90%) |
| 4 | 🟡 `medium` | `invariant` | I5 — Utility class `FullValidationEngine` has excessive fan_out (28) |
| 5 | 🟡 `medium` | `invariant` | I5 — Utility class `StepProcessor` has excessive fan_out (18) |
| 6 | 🟡 `medium` | `invariant` | I3 — Utility class `TerminationReason` has reasoning keyword `reason` in name |
| 7 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanRecordValidationResult` has reasoning keyword `plan` in name |
| 8 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanAdjustment` has reasoning keyword `plan` in name |
| 9 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanPrompt` has reasoning keyword `plan` in name |
| 10 | 🟡 `medium` | `invariant` | I5 — Utility class `ReflectionLoop` has excessive fan_out (33) |
| 11 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanRepair` has reasoning keyword `plan` in name |
| 12 | 🟡 `medium` | `invariant` | I5 — Utility class `PlanRepair` has excessive fan_out (21) |
| 13 | 🟡 `medium` | `invariant` | I5 — Utility class `FullDriftDetector` has excessive fan_out (18) |
| 14 | 🟡 `medium` | `invariant` | I5 — Utility class `AgentState` has excessive fan_out (13) |
| 15 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanValidator` has reasoning keyword `plan` in name |
| 16 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanBreakageReport` has reasoning keyword `plan` in name |
| 17 | 🟡 `medium` | `invariant` | I3 — Utility class `SubgoalPlanner` has reasoning keyword `plan` in name |
| 18 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanGenerator` has reasoning keyword `plan` in name |
| 19 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanMemorySnapshot` has reasoning keyword `plan` in name |
| 20 | 🟡 `medium` | `invariant` | I3 — Utility class `RepairPlan` has reasoning keyword `plan` in name |
| 21 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanSummary` has reasoning keyword `plan` in name |
| 22 | 🟡 `medium` | `invariant` | I5 — Utility class `SummarisationRules` has excessive fan_out (13) |
| 23 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanSegmentValidator` has reasoning keyword `plan` in name |
| 24 | 🟡 `medium` | `invariant` | I5 — Utility class `AgentLoopV2` has excessive fan_out (34) |
| 25 | 🟡 `medium` | `dead-code` | Unreferenced class: `AgentLoopV2` (utility) |
| 26 | 🟡 `medium` | `invariant` | I5 — Utility class `DriftDetector` has excessive fan_out (18) |
| 27 | 🟡 `medium` | `dead-code` | Unreferenced class: `DriftDetector` (utility) |
| 28 | 🟡 `medium` | `dead-code` | Unreferenced class: `PlanExecutor` (infrastructure) |
| 29 | 🟡 `medium` | `dead-code` | Unreferenced class: `CoreStepExecutor` (infrastructure) |
| 30 | 🟡 `medium` | `invariant` | I5 — Utility class `EvictionRules` has excessive fan_out (14) |
| 31 | 🟡 `medium` | `invariant` | I5 — Utility class `SubgoalManager` has excessive fan_out (14) |
| 32 | 🟡 `medium` | `dead-code` | Unreferenced class: `AgentRuntime` (infrastructure) |
| 33 | 🟡 `medium` | `dead-code` | Unreferenced class: `EvictionRules` (utility) |
| 34 | 🟡 `medium` | `dead-code` | Unreferenced class: `SubgoalManager` (utility) |
| 35 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanSegmentManager` has reasoning keyword `plan` in name |
| 36 | 🟡 `medium` | `dead-code` | Unreferenced class: `PlanSegmentManager` (utility) |
| 37 | 🟡 `medium` | `dead-code` | Unreferenced class: `BaseSkill` (domain) |
| 38 | 🟡 `medium` | `dead-code` | Unreferenced class: `SingleSkillExecutor` (infrastructure) |
| 39 | 🟡 `medium` | `dead-code` | Unreferenced class: `MinimalCoreStepExecutor` (infrastructure) |
| 40 | 🟡 `medium` | `dead-code` | Unreferenced class: `LoopOrchestrator` (utility) |
| 41 | 🟡 `medium` | `dead-code` | Unreferenced class: `PlanTransitionPolicy` (infrastructure) |
| 42 | 🟡 `medium` | `dead-code` | Unreferenced class: `Config` (utility) |
| 43 | 🟡 `medium` | `dead-code` | Unreferenced class: `LLMTransport` (infrastructure) |
| 44 | 🟡 `medium` | `dead-code` | Unreferenced class: `MockLLM` (infrastructure) |
| 45 | 🟡 `medium` | `dead-code` | Unreferenced class: `EnforcedLoopPolicy` (infrastructure) |
| 46 | 🟡 `medium` | `dead-code` | Unreferenced class: `Policy` (infrastructure) |
| 47 | 🟡 `medium` | `dead-code` | Unreferenced class: `TransitionEngine` (utility) |
| 48 | 🟡 `medium` | `invariant` | I3 — Utility class `LocalPlanner` has reasoning keyword `plan` in name |
| 49 | 🟡 `medium` | `dead-code` | Unreferenced class: `Executor` (infrastructure) |
| 50 | 🟡 `medium` | `dead-code` | Unreferenced class: `ForbiddenCapabilityPolicy` (infrastructure) |
| 51 | 🟡 `medium` | `dead-code` | Unreferenced class: `LocalPlanner` (utility) |
| 52 | 🟡 `medium` | `dead-code` | Unreferenced class: `RetryPolicy` (infrastructure) |
| 53 | 🟡 `medium` | `dead-code` | Unreferenced class: `StructuredLogger` (infrastructure) |
| 54 | 🟡 `medium` | `dead-code` | Unreferenced class: `ValidationEngine` (utility) |
| 55 | 🟡 `medium` | `dead-code` | Unreferenced class: `CapabilityRegistry` (utility) |
| 56 | 🟡 `medium` | `dead-code` | Unreferenced class: `Governance` (infrastructure) |
| 57 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanStateValidationError` has reasoning keyword `plan` in name |
| 58 | 🟡 `medium` | `invariant` | I6 — Test class `ToolValidator` is inside `src/` |
| 59 | 🟡 `medium` | `dead-code` | Unreferenced class: `LoopTerminationDecision` (utility) |
| 60 | 🟡 `medium` | `dead-code` | Unreferenced class: `SkillFilter` (domain) |
| 61 | 🟡 `medium` | `dead-code` | Unreferenced class: `SkillRanker` (domain) |
| 62 | 🟡 `medium` | `dead-code` | Unreferenced class: `Telemetry` (infrastructure) |
| 63 | 🟡 `medium` | `invariant` | I3 — Utility class `PlanValidationResult` has reasoning keyword `plan` in name |
| 64 | 🟡 `medium` | `invariant` | I6 — Test class `ToolPromptBuilder` is inside `src/` |
| 65 | 🟡 `medium` | `invariant` | I6 — Test class `ToolSchemaGenerator` is inside `src/` |
| 66 | 🟡 `medium` | `dead-code` | Unreferenced class: `AgentDispatcher` (adapter) |
| 67 | 🟡 `medium` | `dead-code` | Unreferenced class: `DeadCodeIgnore` (domain) |
| 68 | 🟡 `medium` | `dead-code` | Unreferenced class: `MinimalSafetyPolicy` (infrastructure) |
| 69 | 🟡 `medium` | `dead-code` | Unreferenced class: `PlanValidationResult` (utility) |
| 70 | 🔵 `low` | `dead-code` | Unreferenced class: `SignalSource` (domain) |
| 71 | 🔵 `low` | `dead-code` | Unreferenced class: `RecoveryAction` (domain) |
| 72 | 🔵 `low` | `dead-code` | Unreferenced class: `GovernanceError` (domain) |
| 73 | 🔵 `low` | `dead-code` | Unreferenced class: `ExecutionError` (domain) |
| 74 | 🔵 `low` | `dead-code` | Unreferenced class: `MappingError` (domain) |
| 75 | 🔵 `low` | `dead-code` | Unreferenced class: `PlanningError` (domain) |
| 76 | 🔵 `low` | `dead-code` | Unreferenced class: `SemanticError` (domain) |
| 77 | 🔵 `low` | `dead-code` | Unreferenced class: `StateError` (domain) |
| 78 | 🔵 `low` | `dead-code` | Unreferenced class: `LLMError` (domain) |
| 79 | 🔵 `low` | `dead-code` | Unreferenced class: `PlanStateValidationError` (utility) |
| 80 | 🔵 `low` | `dead-code` | Unreferenced class: `SemanticValidationError` (domain) |
| 81 | 🔵 `low` | `dead-code` | Unreferenced class: `SystemError` (domain) |
| 82 | 🔵 `low` | `dead-code` | Unreferenced class: `ToolExecutionError` (infrastructure) |
