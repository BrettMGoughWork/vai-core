# Architecture Audit — Pass 2

> Generated from `docs/architecture.json` (Pass 2 extraction)
> Baseline: `docs/AUDIT_PASS1.md`

---

## Summary: Improvements from Pass 1

| Metric | Pass 1 | Pass 2 | Δ |
|---|---|---|---|
| Packages | 20 | 19 | −1 |
| Classes | 161 | 153 | −8 |
| References | 458 | 438 | −20 |
| Exact duplicate class names | 11 | 3 | −8 ✅ |
| Cross-stratum violations | 3 | **0** | −3 ✅ |
| Legacy files present | Yes | **No** | ✅ |

### What was resolved
- **Legacy package eliminated**: all classes from `legacy/` are gone (AgentConfig, CoreStep, CoreStepExecutor, LoopPolicy legacy copies, PlanSegment legacy copy)
- **ValidationError renamed**: `primitives/runtime/validator.py` → `PrimitiveValidationError` — no more collision with the domain `ValidationError`
- **LoopPolicy deduplicated**: reduced from 3 copies to 1 (only `safety/loop_policy.py` remains)
- **PlanSegment deduplicated**: single canonical copy in `models/plan_segment.py`
- **Subgoal deduplicated**: single canonical copy in `models/subgoal.py`
- **executor_contract.py renamed** to `executor_interface.py` — naming now reflects intent
- **Cross-stratum violations eliminated**: `StepResult → StepOutcome` and related violations are resolved

### What remains
Three duplicate class names remain, one stratum misclassification bug persists in the extraction script, and several high-fan-out entry points still show zero inbound references (expected for top-level orchestrators, but worth confirming).

---

## 1. Duplicate Classes

### 1.1 Exact Duplicates (same class name, multiple files)

| Class | Occurrences | Files |
|---|---|---|
| `Executor` | 2 | `src/execution/executor.py`, `src/execution/executor_interface.py` |
| `StepDispatcher` | 2 | `src/core/planning/dispatch/step_dispatcher.py`, `src/core/state/runtime.py` |
| `SubgoalValidator` | 2 | `src/core/planning/subgoals/validator.py`, `src/core/planning/validators/subgoal_validator.py` |

**Analysis:**

- **`Executor`**: The rename of `executor_contract.py` → `executor_interface.py` did not resolve the duplication — the class `Executor` now exists in both files (fi=2, fo=3 each). One file should define the abstract interface and the other should be deleted or renamed to a concrete implementation.
- **`StepDispatcher`** in `state/runtime.py`: This is a shadow copy with fo=2 (much lower coupling than the canonical `dispatch/step_dispatcher.py` with fo=6). The runtime copy appears to be a stale inner class or artifact.
- **`SubgoalValidator`**: Two separate files with identical fan metrics (fi=2, fo=2 each). One resides in `subgoals/validator.py` (inline with the subgoal module) and one in `validators/subgoal_validator.py` (in the consolidated validator directory). These should be merged into one.

### 1.2 Near-Duplicates (same method signature, different names)

| Method set | Classes | Assessment |
|---|---|---|
| `['run']` | CoreStep, LoopController, LoopOrchestrator, CoreStepExecutor, Rule (+ 6 analyser rules) | Intentional protocol — `run()` as execution interface |
| `['chat']` | ChatProvider, AnthropicClient, DeepSeekClient, GeminiClient, MistralClient, OpenAIClient, QwenClient | Correct provider pattern — `ChatProvider` is the base |
| `['execute']` | PlanExecutor, StepExecutor, Executor×2, MinimalCoreStepExecutor, SingleSkillExecutor | `execute()` is the execution protocol — Executor duplication here is the real issue |
| `['validate']` | SegmentValidator, SubgoalValidator×2, PlanSegmentValidator, PlanValidator, ToolValidator | Correct validator pattern — SubgoalValidator duplication here reflects the exact-duplicate issue |
| `['dispatch']` | AgentDispatcher, SafeStepDispatcher, StepDispatcher×2 | Correct dispatcher pattern — StepDispatcher duplication is the issue |
| `['pre_execute', 'post_execute']` | MinimalSafetyPolicy, SafetyPolicy, ForbiddenCapabilityPolicy, PlanTransitionPolicy | Correct strategy pattern |
| `['generate']` | PlanGenerator, ToolSchemaGenerator | Different domains — naming is distinct enough |
| `['log']` | Logger, StdoutLogger | Correct — StdoutLogger implements Logger |

**Conclusion:** Near-duplicate method sets are largely intentional protocol implementations. The only actionable near-duplicate cases are those already flagged as exact duplicates above.

---

## 2. Misplaced Packages

### 2.1 Stratum Misclassification (script bug)

The extraction script evaluates `src/tools/` before `src/core/` in the stratum rule list, causing all classes under `src/core/tools/` to be tagged as `test` instead of `utility` or `adapter`.

**Affected classes:**

| Class | Actual file | Assigned stratum | Correct stratum |
|---|---|---|---|
| `ToolPromptBuilder` | `src/core/tools/prompt_builder.py` | test | utility |
| `ToolSchemaGenerator` | `src/core/tools/schema.py` | test | utility |
| `ToolValidator` | `src/core/tools/validator.py` | test | utility |

**Fix:** In `tools/dictionary/extract_architecture.py`, move the `tools/` → `test` rule below the `src/core/` → `utility` rule in `STRATUM_RULES`, or use a more specific path pattern (`tests/` rather than `tools/`).

### 2.2 Semantically Misclassified Domain Classes

These are assigned `utility` by path heuristic but represent core domain state:

| Class | File | Assigned | More appropriate |
|---|---|---|---|
| `ConversationState` | `src/core/state/state.py` | utility | domain |
| `AgentRuntime` | `src/core/state/runtime.py` | utility | adapter |
| `CoreStep` | `src/core/planning/core_step.py` | utility | domain |
| `CapabilityRegistry` | `src/core/planning/validators/plan_validation.py` | utility | domain |

These are not bugs in the code, but they inflate the `utility` stratum and make stratum-based dependency checking less precise.

### 2.3 Infrastructure Leaking into Core

| Class | File | Stratum | Issue |
|---|---|---|---|
| `LLMTransport` | `src/core/llm/transport.py` | infrastructure | LLM transport is in `src/core/` — mixing infrastructure concerns into the core package boundary |
| `CoreLLMResponse` | `src/core/llm/types.py` | infrastructure | Infrastructure response type lives in `src/core/` |

The `src/core/llm/` subtree is infrastructure sitting inside the core package. Consider moving to `src/infrastructure/llm/` or establishing a clear `src/core/llm/` as a legitimate adapter boundary.

---

## 3. Dead Code

### 3.1 Truly Unreferenced (fi=0 and fo=0)

These classes have no inbound or outbound cross-class references — they are structurally isolated:

| Class | Stratum | File | Severity |
|---|---|---|---|
| `MinimalSafetyPolicy` | utility | `src/core/planning/safety/minimal_policy.py` | **High** — not referenced anywhere |
| `PlanValidationResult` | utility | `src/core/planning/validators/plan_validation.py` | **High** — result object never used |
| `CheckerContext` | test | `tools/code_analysers/shared/context.py` | Low — test tooling |
| `DeadCodeIgnore` | domain | `src/core/types/validation/deadcode_markers.py` | Marker class — expected |
| `Reporter` | test | `tools/code_analysers/shared/reporter.py` | Low — test tooling |
| `ToolPromptBuilder` | test* | `src/core/tools/prompt_builder.py` | Medium — misclassified + unused |
| `ToolSchemaGenerator` | test* | `src/core/tools/schema.py` | Medium — misclassified + unused |

*Stratum is a script artefact; see §2.1.

### 3.2 Zero Fan-In, High Fan-Out (entry points or dead orchestrators)

These classes reference many others but are not referenced themselves. Most are legitimate entry points or top-level orchestrators; some may be dead:

| Class | fi | fo | File | Likely reason |
|---|---|---|---|---|
| `PlanExecutor` | 0 | 17 | `dispatch/plan_executor.py` | Top-level orchestrator — entry point |
| `CoreStepExecutor` | 0 | 16 | `state/core_step_executor.py` | Execution engine — entry point |
| `SubgoalManager` | 0 | 14 | `subgoals/manager.py` | Lifecycle manager — entry point |
| `AgentRuntime` | 0 | 14 | `state/runtime.py` | Runtime host — entry point |
| `LoopOrchestrator` | 0 | 7 | `orchestration/loop_orchestrator.py` | Loop coordinator — entry point |
| `LocalPlanner` | 0 | 3 | `generator/local_planner.py` | Planner — possibly dead |
| `PlanSegmentManager` | 0 | 11 | `segments/manager.py` | Segment lifecycle — possibly unused |
| `SingleSkillExecutor` | 0 | 9 | `src/execution/singleskillexecutor.py` | Executor variant — possibly dead |
| `MinimalCoreStepExecutor` | 0 | 8 | `src/execution/minimal_executor.py` | Minimal executor — possibly dead |
| `Config` | 0 | 5 | `src/core/config/loader.py` | Config loader — likely factory-loaded |
| `ForwardCapabilityPolicy` | 0 | 3 | `safety/safety_policies.py` | Policy — possibly unused |
| `LoopTerminationDecision` | 0 | 1 | `orchestration/loop_termination.py` | May only be instantiated locally |
| **All 6 LLM clients** | 0 | 11 | `llm/providers/*.py` | Factory-registered — expected |

**Recommendation:** The AST extractor cannot detect factory registration or dependency injection patterns. The fi=0 entries for orchestrators and LLM clients are almost certainly expected. The concern is `MinimalSafetyPolicy`, `SingleSkillExecutor`, `MinimalCoreStepExecutor`, `LocalPlanner`, and `PlanSegmentManager` — these warrant manual confirmation.

### 3.3 Zero Fan-In Domain Errors (uncaught exceptions)

Several domain error classes have fi=0, suggesting they are raised but never caught at the class level:

| Class | File |
|---|---|
| `GovernanceError` | `src/core/types/errors/AgentError.py` |
| `LLMError` | `src/core/types/errors/LLMError.py` |
| `SemanticError` | `src/core/types/errors/AgentError.py` |
| `StateError` | `src/core/types/errors/AgentError.py` |
| `MappingError` | `src/core/types/errors/AgentError.py` |
| `ExecutionError` | `src/core/types/errors/AgentError.py` |
| `PlanningError` | `src/core/types/errors/AgentError.py` |
| `SystemError` | `src/core/types/errors/SystemError.py` |
| `RecoveryAction` | `src/core/types/errors/recovery.py` |

This pattern often indicates error types defined for completeness but never consumed — candidates for removal if no handler exists.

---

## 4. Broken Invariants

### 4.1 Cross-Stratum Violations

**Pass 2 has zero detected cross-stratum violations.** This is a meaningful improvement — the `StepResult → StepOutcome` violation from Pass 1 has been resolved.

### 4.2 Remaining Naming Inconsistencies

| Issue | Evidence |
|---|---|
| `PlanStatus` vs `PlanState` (PREFIX match) | Both in `plan_state.py` — one is enum, one is state machine; naming is close enough to cause confusion |
| `StepStatus` vs `StepState` (PREFIX match) | Same file — same concern |
| `SegmentState` vs `SubgoalState` | Parallel structures but divergent naming conventions (`SubgoalLifecycleState` vs `SegmentState`) |
| `Policy` / `SafetyPolicy` / `MinimalSafetyPolicy` / `LoopPolicy` | Four policy classes with overlapping naming — consider a policy interface hierarchy |
| `CoreStepExecutor` vs `MinimalCoreStepExecutor` | PREFIX — two execution paths for `CoreStep`; unclear distinction from naming alone |
| `SegmentValidator` vs `PlanSegmentValidator` vs `SubgoalValidator` (×2) | Validator family lacks consistent naming prefix |

### 4.3 Structural Drift

| Observation | Location | Risk |
|---|---|---|
| Two `validators/` directories exist | `subgoals/validator.py` and `validators/subgoal_validator.py` | SubgoalValidator duplicate is a direct result |
| `StepDispatcher` defined inside `runtime.py` | `src/core/state/runtime.py` | Suggests copy-paste from `dispatch/` without cleanup |
| `Executor` defined twice after rename | `executor.py` and `executor_interface.py` | Interface rename was incomplete |
| `src/core/llm/` contains infrastructure | `transport.py`, `types.py`, `providers/` | Boundary leak — core should not own infra |

---

## 5. Refactor Priority Ranking

Issues ranked by severity (fan_in × impact, cross-stratum weight, duplication risk).

### 🔴 HIGH — Address before next structural change

| # | Issue | Classes | Evidence | Action |
|---|---|---|---|---|
| 1 | **Executor not deduplicated** | `Executor` ×2 (fi=2+2, fo=3+3) | File rename did not remove the duplicate class | Delete `Executor` from `executor.py` or `executor_interface.py`; one must become the concrete impl |
| 2 | **StepDispatcher shadow in runtime.py** | `StepDispatcher` ×2 (fo=6 vs fo=2) | Low-coupling copy in state layer; dispatch layer has the canonical | Remove `StepDispatcher` from `runtime.py` or rename to `RuntimeStepDispatcher` |
| 3 | **SubgoalValidator split across two directories** | `SubgoalValidator` ×2 (fi=2+2, fo=2+2) | Both `subgoals/validator.py` and `validators/subgoal_validator.py` exist | Consolidate in one location; delete the other |

### 🟡 MEDIUM — Address in next refactor cycle

| # | Issue | Classes | Evidence | Action |
|---|---|---|---|---|
| 4 | **Script stratum bug: src/core/tools/** | ToolPromptBuilder, ToolSchemaGenerator, ToolValidator | Classified as `test`; should be `utility` | Fix `STRATUM_RULES` ordering in `extract_architecture.py` |
| 5 | **MinimalSafetyPolicy completely unreferenced** | `MinimalSafetyPolicy` (fi=0, fo=0) | No callers, no dependencies | Confirm if intentional stub; delete if not |
| 6 | **PlanValidationResult unreferenced** | `PlanValidationResult` (fi=0, fo=0) | Result object never consumed | Confirm usage; delete if unused |
| 7 | **Infrastructure in src/core/llm/** | LLMTransport, CoreLLMResponse, provider clients | Infrastructure concerns in core package | Move to `src/infrastructure/llm/` or formalise as an adapter boundary |
| 8 | **PlanStatus / PlanState naming** | fi=10/fo=6 and fi=9/fo=6 | Highly referenced; confusing naming | Rename one: `PlanStatus` (enum) and `PlanLifecycle` or `PlanRecord` (state object) |
| 9 | **SingleSkillExecutor / MinimalCoreStepExecutor** | Both fi=0 | Executor variants with no inbound refs | Confirm if registered via factory; delete if dead |

### 🟢 LOW — Track but no immediate action required

| # | Issue | Evidence | Action |
|---|---|---|---|
| 10 | **LLM provider clients fi=0** | All 6 clients | Expected — factory/DI registration pattern | No action; document registration point |
| 11 | **Domain error classes fi=0** | GovernanceError, LLMError, etc. | Likely raised but not caught by name | Review if catch-blocks use base class only |
| 12 | **PlanExecutor / CoreStepExecutor / SubgoalManager / AgentRuntime fi=0** | High fo, no inbound refs | Entry-point orchestrators; DI pattern | Document in architecture notes as top-level roots |
| 13 | **ConversationState, CoreStep, AgentRuntime stratum** | Assigned utility; semantically domain/adapter | Script heuristic limitation | Address when stratum rules are refined |
| 14 | **SegmentValidator vs PlanSegmentValidator naming** | Near-duplicate names | Different scopes but confusingly similar | Consider `PlanSegmentValidator` → `SegmentBoundaryValidator` |

---

*Report generated from Pass 2 extraction: 19 packages, 153 classes, 438 references.*
