# Architecture Audit — Pass 3

**Extracted:** 19 packages · 150 classes · 426 references
**Baseline (Pass 2):** 19 packages · 153 classes · 438 references
**Delta:** −3 classes · −12 references

---

## Progress vs Pass 2

| High-Priority Item (Pass 2) | Status |
|---|---|
| `Executor` duplicate (`executor.py` / `executor_interface.py`) | ✅ Resolved |
| `StepDispatcher` shadow copy in `runtime.py` | ✅ Resolved |
| `SubgoalValidator` duplicate (`subgoals/validator.py` / `validators/subgoal_validator.py`) | ❌ Still open |
| `CoreStepExecutor → LLMTransport` cross-stratum violation | 🆕 **New regression** |

Net: 2 of 3 Pass 2 High items resolved. 1 new High item introduced.

---

## 1. Duplicate Classes

### 1.1 Exact Duplicates

| Class | Files |
|---|---|
| `SubgoalValidator` | `src/core/planning/subgoals/validator.py` · `src/core/planning/validators/subgoal_validator.py` |

One copy must be deleted and all import sites updated to the canonical path. The `validators/` directory is the more consistent home given the existing `PlanValidator` there.

### 1.2 Near-Duplicates (Structural Overlap)

| Class A | Class B | Overlap |
|---|---|---|
| `CoreStepExecutor` (`src/core/state/`) | `MinimalCoreStepExecutor` (`src/execution/`) | Both implement step execution; fo=16 vs fo=8 — likely an extraction residual |
| `StepExecutor` (`runtime.py`, Protocol) | `CoreStepExecutor` (`core_step_executor.py`) | Protocol vs concrete; acceptable if intentional |
| `PlanState` (fo=6, fi=9) | `PlanStatus` (fo=6, fi=10) | Co-located in `plan_state.py`; naming may cause confusion |

---

## 2. Misplaced Packages

### 2.1 Stratum Tool Bug (Extractor Artefact)

The extraction script assigns `test` stratum to any path containing `tools/`. This incorrectly classifies production source files in `src/core/tools/`:

| Class | Actual Stratum | Assigned Stratum | File |
|---|---|---|---|
| `ToolPromptBuilder` | utility | test | `src/core/tools/prompt_builder.py` |
| `ToolSchemaGenerator` | utility | test | `src/core/tools/schema.py` |
| `ToolValidator` | utility | test | `src/core/tools/validator.py` |

**Fix:** Narrow the extractor's test rule from `tools/` → `tests/` (note trailing `s`). See `tools/dictionary/extract_architecture.py` stratum logic.

### 2.2 Utility Classes That Should Be Domain

| Class | Assigned | Reason for Concern |
|---|---|---|
| `SubgoalState` | utility | Pure state model; no infrastructure dependency |
| `SegmentState` | utility | Same |
| `ConversationState` | utility | Stateful session model; fan-in=9 suggests core domain use |
| `SafetyContext` | utility | Policy evaluation context — arguably domain |

These are low-severity; naming/path conventions are consistent. Flag for review if domain purity is enforced.

---

## 3. Dead Code

### 3.1 Zero Fan-In, Zero Fan-Out (Truly Unreferenced)

| Class | Stratum | File |
|---|---|---|
| `MinimalSafetyPolicy` | utility | `src/core/planning/safety/safety_policies.py` |
| `PlanValidationResult` | utility | `src/core/planning/validators/plan_validator.py` |
| `CheckerContext` | test | `tools/code_analysers/shared/checker.py` |
| `DeadCodeIgnore` | test | `tools/code_analysers/deadcode/analyser.py` |
| `Reporter` | test | `tools/code_analysers/shared/reporter.py` |
| `ToolPromptBuilder` | (see §2.1) | `src/core/tools/prompt_builder.py` |
| `ToolSchemaGenerator` | (see §2.1) | `src/core/tools/schema.py` |

`MinimalSafetyPolicy` and `PlanValidationResult` are the actionable items — they are in production `src/` and appear genuinely unused.

### 3.2 Zero Fan-In, High Fan-Out (DI Roots — Expected)

These are entry points registered via dependency injection. `fi=0` is expected and does **not** indicate dead code.

| Class | fo | File |
|---|---|---|
| `PlanExecutor` | 17 | `src/core/planning/dispatch/plan_executor.py` |
| `CoreStepExecutor` | 16 | `src/core/state/core_step_executor.py` |
| `SubgoalManager` | 14 | `src/core/planning/subgoals/manager.py` |
| `AgentRuntime` | 14 | `src/core/state/runtime.py` |
| `LoopOrchestrator` | 7 | `src/core/planning/orchestration/loop_orchestrator.py` |
| `PlanSegmentManager` | 11 | `src/core/planning/segments/manager.py` |
| `SingleSkillExecutor` | 9 | `src/execution/singleskillexecutor.py` |
| `MinimalCoreStepExecutor` | 8 | `src/execution/minimal_executor.py` |
| All 6 LLM provider clients | 11 each | `src/core/llm/providers/` |

---

## 4. Broken Invariants

### 4.1 Cross-Stratum Violations

| Source | Target | Direction | Violation |
|---|---|---|---|
| `CoreStepExecutor` (utility) | `LLMTransport` (infrastructure) | import + call | **Utility reaching into infrastructure** |

This is a **regression introduced in Pass 3**. A utility-stratum executor should not hold a direct reference to an infrastructure transport. Correct approach: inject `LLMTransport` via a domain interface (e.g., `ChatProvider`) and depend on the abstraction, not the concrete transport.

Pass 2 had 0 cross-stratum violations. This is the only new one.

### 4.2 Naming Inconsistencies

| Pattern | Classes |
|---|---|
| Mixed `Error`/`Exception` suffix | `AgentError`, `SemanticError`, `StateError` vs `SubgoalError`, `SegmentError`, `ToolExecutionError` |
| `Manager` vs `Orchestrator` vs `Controller` | `SubgoalManager`, `PlanSegmentManager`, `LoopOrchestrator`, `LoopController` — distinct responsibilities but inconsistent naming tier |
| `State` vs `LifecycleState` vs `Status` | `PlanState`, `PlanStatus`, `SubgoalLifecycleState`, `StepStatus`, `StepState` — overloaded suffixes |

### 4.3 Structural Drift

- `SafeFailure` (fi=8, fo=1) lives in `src/execution/` but is referenced heavily across planning. Should be in `src/core/types/errors/`.
- `RecoveryAction` (fi=0, fo=6, domain) has no inbound references — it is produced but never consumed, suggesting an incomplete recovery pipeline.

---

## 5. Refactor Priority Ranking

### 🔴 High

| # | Issue | Severity Signal | Action |
|---|---|---|---|
| H1 | `CoreStepExecutor → LLMTransport` cross-stratum violation | **Regression**; utility→infra coupling | Inject via `ChatProvider` interface |
| H2 | `SubgoalValidator` duplicated in two packages | fan-in inflated across both copies | Delete one, consolidate imports |

### 🟡 Medium (Backlog)

| # | Issue | Signal | Suggested Action |
|---|---|---|---|
| M1 | Extractor misclassifies `src/core/tools/` as `test` | 3 classes wrong stratum | Fix extractor: `tools/` → `tests/` in test rule |
| M2 | `MinimalSafetyPolicy` unreferenced (fi=0, fo=0) | Dead code in `src/` | Remove or wire into safety chain |
| M3 | `PlanValidationResult` unreferenced (fi=0, fo=0) | Dead code in `src/` | Remove or document intent |
| M4 | `RecoveryAction` produced but never consumed (fi=0) | Incomplete pipeline | Wire into error recovery or remove |
| M5 | `SafeFailure` mislocated (`src/execution/`, fi=8) | Referenced across planning layer | Move to `src/core/types/errors/` |

### 🟢 Low (Backlog)

| # | Issue | Signal | Suggested Action |
|---|---|---|---|
| L1 | `PlanState` / `PlanStatus` naming ambiguity (same file, similar fan) | Cognitive overhead | Rename one to clarify role |
| L2 | `SubgoalState`, `SegmentState`, `ConversationState` assigned utility stratum | Arguably domain | Review stratum assignments |
| L3 | Naming inconsistency: `Error` vs `Exception` suffix | Style drift | Standardise across `src/core/types/errors/` |
| L4 | `LoopOrchestrator` vs `LoopController` — unclear responsibility split | Structural drift | Document or merge |
| L5 | `CoreStepExecutor` / `MinimalCoreStepExecutor` overlap | fo=16 vs fo=8 | Confirm intentional split; document if so |

---

## Appendix: High-Traffic Stable Anchors

These classes have high combined fan-in+fan-out and are structurally correct. They should be treated as **stable API surfaces** — changes carry wide blast radius.

| Class | fi | fo | Stratum |
|---|---|---|---|
| `StepResult` | 23 | 6 | domain |
| `Plan` | 20 | 1 | domain |
| `StepOutcome` | 19 | 7 | domain |
| `StepState` | 16 | 8 | domain |
| `AgentError` | 16 | 1 | domain |
| `PlanSegment` | 14 | 3 | domain |
| `ValidationError` | 14 | 2 | domain |
| `ChatProvider` | 13 | 5 | infrastructure |
| `CoreResult` | 13 | 3 | domain |
| `PlanValidationError` | 13 | 1 | domain |
