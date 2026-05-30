# Architecture Audit — Pass 1

**Source:** `docs/architecture.json`
**Branch:** `refactor/janitor-2`
**Classes extracted:** 161 | **Packages:** 20 | **References:** 458

---

## 1. Duplicate Classes

### 1.1 Exact Duplicates (identical class name, multiple files)

| Class | Count | Files |
|---|---|---|
| `AgentConfig` | 2 | `legacy/config.py`, `src/core/config/model.py` |
| `CoreStep` | 2 | `legacy/step.py`, `src/core/planning/core_step.py` |
| `CoreStepExecutor` | 2 | `legacy/corestep.py`, `src/core/state/core_step_executor.py` |
| `Executor` | 2 | `src/execution/executor.py`, `src/execution/executor_contract.py` |
| `GovernanceError` | 2 | `src/core/types/errors/AgentError.py`, `src/governance/errors.py` |
| `LoopPolicy` | **3** | `legacy/config.py`, `src/core/planning/orchestration/loop_controller.py`, `src/core/planning/safety/loop_policy.py` |
| `PlanSegment` | 2 | `src/core/planning/models/plan_segment.py`, `src/core/planning/segments/model.py` |
| `StepDispatcher` | 2 | `src/core/planning/dispatch/step_dispatcher.py`, `src/core/state/runtime.py` |
| `Subgoal` | 2 | `src/core/planning/models/subgoal.py`, `src/core/planning/subgoals/model.py` |
| `SubgoalValidator` | 2 | `src/core/planning/subgoals/validator.py`, `src/core/planning/validators/subgoal_validator.py` |
| `ValidationError` | 2 | `src/core/types/errors/ValidationError.py`, `src/primitives/runtime/validator.py` |

**Notes:**
- The `legacy/` duplicates (`AgentConfig`, `CoreStep`, `CoreStepExecutor`, `LoopPolicy`) represent undeleted predecessors of their `src/` counterparts. They continue to accumulate fan-in (AgentConfig legacy: fi=12), indicating they are still being resolved by the reference graph and may still be imported transitively.
- `Executor` is duplicated within the same package (`src/execution/`) between an implementation file and a contract file — the contract should define an interface, not re-declare the class.
- `PlanSegment` and `Subgoal` each exist in both `models/` (domain stratum) and their respective subdirectory `model.py` (utility stratum), creating stratum ambiguity for the same concept.
- `GovernanceError` is declared in `src/core/types/errors/AgentError.py` (domain) and independently in `src/governance/errors.py` (adapter), meaning the error type has split across strata.

### 1.2 Near-Duplicates (identical public method sets, different names)

| Shared Method(s) | Classes |
|---|---|
| `run` | `CoreStep`, `CoreStepExecutor` (×2), `LoopController`, `LoopOrchestrator`, `ToolSpec`, `Rule`, + 6 rule classes |
| `execute` | `PlanExecutor`, `StepExecutor`, `Executor` (×2), `MinimalCoreStepExecutor`, `SingleSkillExecutor` |
| `dispatch` | `AgentDispatcher`, `SafeStepDispatcher`, `StepDispatcher` (×2) |
| `validate` | `SegmentValidator`, `SubgoalValidator` (×2), `PlanSegmentValidator`, `PlanValidator`, `ToolValidator` |
| `chat` | `ChatProvider`, `AnthropicClient`, `DeepSeekClient`, `GeminiClient`, `MistralClient`, `OpenAIClient`, `QwenClient` |
| `generate` | `PlanGenerator`, `ToolSchemaGenerator` |
| `pre_execute` + `post_execute` | `MinimalSafetyPolicy`, `SafetyPolicy`, `ForbiddenCapabilityPolicy`, `PlanTransitionPolicy` |
| `log` | `Logger`, `StdoutLogger` |
| `to_dict` | `Plan`, `ValidationError` |
| `get` | `Config`, `RetryPolicy` |

**Notable:** The `execute`/`run`/`dispatch` families indicate a fragmented executor hierarchy with no shared base class enforcing the contract. Six LLM provider clients all expose only `chat` — they correctly share `ChatProvider` as a base, but none of the other executor families share a base.

---

## 2. Misplaced Packages

### 2.1 `src/tools/` Classified as `test` Stratum

The extraction rules assigned `test` to `src/tools/` because the rule for `tools/` was matched before the `src/` prefix was considered. The three classes in `src/tools/` — `ToolPromptBuilder`, `ToolSchemaGenerator`, `ToolValidator` — are production code serving the adapter layer, not test infrastructure. All three have fi=0, compounding the visibility problem.

| Class | File | Assigned Stratum | Correct Stratum |
|---|---|---|---|
| `ToolPromptBuilder` | `src/tools/prompt_builder.py` | test | adapter |
| `ToolSchemaGenerator` | `src/tools/schema.py` | test | adapter |
| `ToolValidator` | `src/tools/validator.py` | test | adapter |

### 2.2 `StepOutcome` in Utility Stratum Used by Domain

`StepOutcome` (utility, `src/core/state/outcome.py`, fi=21) is referenced by `StepResult` (domain, `src/core/types/step_result.py`). Domain types should not depend on utility-layer state classes. `StepOutcome` has the highest fan-in of any utility class (21), which means this misplacement is widely load-bearing.

### 2.3 `GovernanceError` Split Across Domain and Adapter

`GovernanceError` is declared in `src/core/types/errors/AgentError.py` (domain) and again in `src/governance/errors.py` (adapter). An error type defined in domain should not be re-declared in adapter. The domain copy has fi=0 and is likely unreachable; the adapter copy has fi=0 also. Neither is referenced.

### 2.4 `CoreLLMResponse` in Infrastructure, Imported by Domain Candidates

`CoreLLMResponse` lives in `src/core/llm/types.py` (infrastructure, fi=2). Its name prefix `Core` implies a domain type, but its location is infrastructure. If callers treat it as a domain response type, this creates an implicit infra→domain coupling in the wrong direction.

### 2.5 `Policy` (`src/policy/policy.py`) is Isolated Utility

`Policy` (utility, fi=0, fo=4) is the sole class in an entire top-level package (`src/policy/`). It has no inbound references. Its presence as a standalone package rather than within `src/core/planning/safety/` (where all other policy classes live) represents structural drift.

---

## 3. Dead Code

### 3.1 Zero Fan-In — Production Classes with No Inbound References

The following non-test, non-legacy classes have fi=0, meaning no other class in the codebase references them by name.

#### High Severity (fi=0, fo≥8 — large, unreachable)

| Class | File | fan_out | stratum |
|---|---|---|---|
| `AgentRuntime` | `src/core/state/runtime.py` | 14 | utility |
| `PlanExecutor` | `src/core/planning/dispatch/plan_executor.py` | 17 | utility |
| `SubgoalManager` | `src/core/planning/subgoals/manager.py` | 14 | utility |
| `PlanSegmentManager` | `src/core/planning/segments/manager.py` | 11 | utility |
| `CoreStepExecutor` | `src/core/state/core_step_executor.py` | 16 | utility |
| `MinimalCoreStepExecutor` | `src/execution/minimal_executor.py` | 8 | utility |
| `SingleSkillExecutor` | `src/execution/singleskillexecutor.py` | 9 | utility |
| `LoopOrchestrator` | `src/core/planning/orchestration/loop_orchestrator.py` | 7 | utility |

These classes have significant internal complexity (high fan_out) but receive zero references. They are either entry points wired at runtime (outside the static graph), or they are dead execution paths.

#### Medium Severity (fi=0, fo 1–7)

| Class | File | fan_out | stratum |
|---|---|---|---|
| `AnthropicClient` | `src/core/llm/providers/anthropic.py` | 11 | infrastructure |
| `GeminiClient` | `src/core/llm/providers/gemini.py` | 11 | infrastructure |
| `MistralClient` | `src/core/llm/providers/mistral.py` | 11 | infrastructure |
| `OpenAIClient` | `src/core/llm/providers/openai.py` | 11 | infrastructure |
| `QwenClient` | `src/core/llm/providers/qwen.py` | 11 | infrastructure |
| `DeepSeekClient` | `src/core/llm/providers/deepseek.py` | 7 | infrastructure |
| `BaseSkill` | `src/primitives/base.py` | 10 | domain |
| `Config` | `src/core/config/loader.py` | 5 | utility |
| `LocalPlanner` | `src/core/planning/generator/local_planner.py` | 3 | utility |
| `LoopTerminationDecision` | `src/core/planning/orchestration/loop_termination.py` | 1 | utility |
| `ForbiddenCapabilityPolicy` | `src/core/planning/safety/safety_policies.py` | 3 | utility |
| `MinimalSafetyPolicy` | `src/core/planning/safety/minimal_policy.py` | 0 | utility |
| `PlanTransitionPolicy` | `src/core/planning/safety/safety_policies.py` | 6 | utility |
| `Policy` | `src/policy/policy.py` | 4 | utility |
| `RetryPolicy` | `src/execution/retry/retry_policy.py` | 3 | utility |
| `Governance` | `src/governance/schema.py` | 2 | adapter |
| `Telemetry` | `src/telemetry/telemetry.py` | 1 | infrastructure |
| `StructuredLogger` | `src/observability/logger.py` | 3 | infrastructure |

**All 6 LLM provider clients have fi=0.** They are referenced through `ChatProvider` (fi=13) but not by class name. This is expected if construction is via factory, but the `LLMFactory`/`LLMBuilder` classes are not present in the extracted class list, indicating they may be module-level functions rather than classes and thus invisible to the extractor.

#### Zero Fan-In Domain Error Types (likely defined but never caught by name)

| Class | File |
|---|---|
| `ExecutionError` | `src/core/types/errors/AgentError.py` |
| `GovernanceError` | `src/core/types/errors/AgentError.py` |
| `LLMError` | `src/core/types/errors/LLMError.py` |
| `MappingError` | `src/core/types/errors/AgentError.py` |
| `PlanningError` | `src/core/types/errors/AgentError.py` |
| `RecoveryAction` | `src/core/types/errors/recovery.py` |
| `SemanticError` | `src/core/types/errors/AgentError.py` |
| `SemanticValidationError` | `src/primitives/runtime/semantic.py` |
| `SkillFilter` | `src/primitives/runtime/skill_filter.py` |
| `SkillRanker` | `src/primitives/runtime/skill_ranker.py` |
| `StateError` | `src/core/types/errors/AgentError.py` |
| `SystemError` | `src/core/types/errors/SystemError.py` |

### 3.2 Zero Fan-In — Legacy Files (should be deleted)

| Class | File |
|---|---|
| `CoreStepExecutor` | `legacy/corestep.py` |

The legacy `CoreStep` and `AgentConfig` have fi>0 due to the reference graph treating all same-named classes as one target. The `CoreStepExecutor` in legacy has fi=0 even under this collapsing, confirming it is truly unreachable.

### 3.3 Dead but Referenced by Name Only (fi>0, fo=0 — leaf sinks)

These classes are referenced but call nothing themselves — they are pure data/enum types or terminal error classes. They are not dead code but are worth noting for completeness: `CircuitBreaker` (fi=3, fo=0), `DegradedModeController` (fi=3, fo=0), `PoisonJobDetector` (fi=3, fo=0), `SelfHealingController` (fi=3, fo=0), `Violation` (fi=8, fo=0).

---

## 4. Broken Invariants

### 4.1 Cross-Stratum Violations

#### domain → utility (1 confirmed violation)

| Source | Source Stratum | Target | Target Stratum | Type |
|---|---|---|---|---|
| `StepResult` | domain | `StepOutcome` | utility | call |

`StepResult` (`src/core/types/step_result.py`) references `StepOutcome` (`src/core/state/outcome.py`). Domain types must not depend on utility-layer runtime state. `StepOutcome` carries fi=21 — it is deeply embedded and this violation is structurally load-bearing.

#### Implicit: domain classes depend on utility `ConversationState` (fi=12)

`ConversationState` (utility, `src/core/state/state.py`) is referenced by 12 classes. If any of those callers are domain-stratum classes, this represents additional domain→utility coupling not surfaced by the single-hop violation check.

### 4.2 Forbidden Dependencies

#### `GovernanceError` redeclared in adapter after definition in domain

The canonical location for error types is `src/core/types/errors/`. `GovernanceError` was declared there (domain) and then re-declared in `src/governance/errors.py` (adapter). Consumers cannot know which to import without examining both files.

#### `ValidationError` declared in two domain packages

`src/core/types/errors/ValidationError.py` and `src/primitives/runtime/validator.py` each declare a class named `ValidationError` in the domain stratum. With fi=14 for both, callers are resolving this ambiguously.

#### `PlanSegment` and `Subgoal` duplicated across model boundaries

`PlanSegment` exists in `src/core/planning/models/plan_segment.py` (domain) and `src/core/planning/segments/model.py` (utility). `Subgoal` exists in `src/core/planning/models/subgoal.py` (domain) and `src/core/planning/subgoals/model.py` (utility). The segments and subgoals subdirectories each maintain their own copy of the model they manage, diverging from the canonical model definitions in `models/`.

### 4.3 Naming Inconsistencies

| Pattern | Instances |
|---|---|
| `LoopPolicy` declared 3 times | `legacy/config.py`, `loop_controller.py`, `loop_policy.py` |
| `Executor` concept spread across 6 names | `Executor`, `CoreStepExecutor`, `MinimalCoreStepExecutor`, `SingleSkillExecutor`, `StepExecutor`, `PlanExecutor` |
| `*Validator` with identical `validate` method | `SegmentValidator`, `SubgoalValidator`×2, `PlanSegmentValidator`, `PlanValidator`, `ToolValidator` — no shared base |
| Config hierarchy fragmented | `Config`, `AgentConfig`, `CoreConfig`, `LLMConfig`, `LoopPolicyConfig` — 5 config classes, no visible base |
| `PlanStatus` vs `PlanState` — prefix collision | Both in `src/core/planning/models/plan_state.py`, near-identical names for distinct concepts |
| `StepStatus` vs `StepState` — same pattern | Both in `src/core/planning/models/step_state.py` |

### 4.4 Structural Drift

- **`src/policy/` as a top-level package for one class:** `Policy` (`src/policy/policy.py`) is the only class in its package and has fi=0. All other policy-related classes live in `src/core/planning/safety/`. This package should not exist independently.
- **`src/core/state/runtime.py` contains two classes:** `StepDispatcher` and `StepExecutor` are defined in `runtime.py`, but identically-named classes exist elsewhere (`dispatch/step_dispatcher.py`). The `runtime.py` definitions are shadowed and likely stale.
- **`src/tools/` classified incorrectly:** The package boundary between `src/tools/` (production adapters) and `tools/` (dev/analysis scripts) is ambiguous by name. This causes stratum misclassification and reduces discoverability.
- **`src/primitives/_dev/test_math.py`:** A development scratch file present in the source tree.

---

## 5. Refactor Priority Ranking

Ranked by combined severity: stratum violation weight + fan_in of affected class + fan_out of affected class.

### Priority 1 — Critical (stratum violation on high-traffic classes)

| # | Issue | Classes Affected | Evidence |
|---|---|---|---|
| 1 | `StepResult` (domain) depends on `StepOutcome` (utility) | `StepResult` fi=23, `StepOutcome` fi=21 | Only confirmed cross-stratum violation; both classes are the most-referenced in codebase |
| 2 | `ValidationError` declared in two domain packages | fi=14 each | Callers cannot know which to import; 14 referencing classes are resolving ambiguously |
| 3 | `PlanSegment` duplicated across domain and utility | fi=14 each | The canonical model and the manager's local copy drift independently |

### Priority 2 — High (dead high-fanout classes)

| # | Issue | Classes Affected | Evidence |
|---|---|---|---|
| 4 | `PlanExecutor` unreachable (fi=0, fo=17) | `PlanExecutor` | If this is the primary execution path, its fi=0 means the wiring is invisible to static analysis or it is dead |
| 5 | `AgentRuntime` unreachable (fi=0, fo=14) | `AgentRuntime` | Same concern — largest coordinator class with no inbound references |
| 6 | `CoreStepExecutor` duplicated and both fi=0 | both `CoreStepExecutor` | 32 combined fan_out units pointing at classes from an unreachable class |
| 7 | `SubgoalManager` + `PlanSegmentManager` both fi=0 | fi=0, fo=14 and fo=11 | Manager-layer classes with no callers |

### Priority 3 — Medium (naming and structural fragmentation)

| # | Issue | Classes Affected | Evidence |
|---|---|---|---|
| 8 | `LoopPolicy` triplication | 3 definitions across legacy, orchestration, safety | fi=4 each — consumers resolve to all three |
| 9 | `Subgoal` duplicated across models/ and subgoals/ | fi=11 each | Same as PlanSegment concern |
| 10 | `Executor` class in both `executor.py` and `executor_contract.py` | fi=2 each | Same package, same name, different intents |
| 11 | 5 config classes with no shared base | `Config`, `AgentConfig`, `CoreConfig`, `LLMConfig`, `LoopPolicyConfig` | Configuration schema is untyped at the top |
| 12 | 6 executor variants with no shared base | `Executor`×2, `CoreStepExecutor`×2, `MinimalCoreStepExecutor`, `SingleSkillExecutor` | All expose `execute` with no common interface |

### Priority 4 — Low (cleanup / hygiene)

| # | Issue | Classes Affected | Evidence |
|---|---|---|---|
| 13 | All `legacy/` classes still active in reference graph | `AgentConfig`, `CoreStep`, `LoopPolicy` in legacy/ | Should be deleted once src/ replacements confirmed |
| 14 | `src/policy/` should be merged into `src/core/planning/safety/` | `Policy` fi=0 | Isolated package, no callers |
| 15 | 6 LLM provider clients all fi=0 | All provider clients | Expected if factory-constructed, but worth confirming |
| 16 | `StepDispatcher` redefined in `runtime.py` | | Shadowed by `dispatch/step_dispatcher.py` |
| 17 | `src/tools/` stratum misclassification | `ToolPromptBuilder`, `ToolSchemaGenerator`, `ToolValidator` | All fi=0; misclassified as test |
| 18 | `src/primitives/_dev/test_math.py` in source tree | `test_math.py` | Dev scratch file |

---

*Generated by: `tools/dictionary/extract_architecture.py` (Pass 1 extraction) + manual audit of `docs/architecture.json`*
