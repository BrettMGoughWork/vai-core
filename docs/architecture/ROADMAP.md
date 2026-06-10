# Project roadmap
- This roadmap is a guide rather than an explicit checklist 
- Changes, challenges, suggestions are encouraged. The expectation is that phases and strata are goals to be met, and tasks a list of breadcrumbs to reach those goals 
- Expect entire phases to be inserted where gaps in the plan may exist
- Where required, detail is generally added prior to the next phase or stratum

## STRATUM 1 - Execution Substrate
*Invariant*: Stratum 1 must remain deterministic, reactive, and free of long-horizon reasoning

### PHASE 1.1 — Core Runtime Foundation (with BaseSkill + ToolSpec)

✅ 1.1.1. Define core config model — LLM, timeouts, limits, skill paths.  
✅ 1.1.2. Define ToolSpec class — name, description, schema, side‑effects, category.  
✅ 1.1.3. Define BaseSkill class — handler, schema generation, validation, execution.  
✅ 1.1.4. Define skill categories + side‑effect flags — io, network, fs, dangerous.  
✅ 1.1.5. Implement schema generator — from handler signature → JSON schema.  
✅ 1.1.6. Implement structural validator — types, required fields.  
✅ 1.1.7. Implement semantic validator hook — domain‑specific checks.  
✅ 1.1.8. Implement canonicalisation layer — trim, normalise, lower.  
✅ 1.1.9. Implement LLM transport wrapper — single entrypoint.  
✅ 1.1.10. Implement tool selection governance — allowed tools, categories.  
✅ 1.1.11. Implement tool execution engine — call handler, wrap errors.  
✅ 1.1.12. Define CoreResult type — success, error, metadata.

---

### PHASE 1.2 — State Machine & Loop Semantics
*Depends On*: PHASE 1.1

✅ 1.2.1. Define ConversationState — input, history, last tool call, metadata.  
✅ 1.2.2. Implement CoreStep(state) — one LLM → tool → result transition.  
✅ 1.2.3. Classify step outcomes — success, recoverable, fatal, noop.  
✅ 1.2.4. Define isdone(state) — goal reached, limits hit.  
✅ 1.2.5. Implement CoreStep loop(state, policy) — while not done → step.  
✅ 1.2.6. Define loop policy model — max steps, wall time, errors.  
✅ 1.2.7. Add per‑step timeout — kill slow steps.  
✅ 1.2.8. Add per‑loop timeout — kill runaway loops.  
✅ 1.2.9. Add loop trace log — append step summaries.

---

### PHASE 1.3 - Execution Semantics
*Depends On*: PHASE 1.2  
*Note*: This phase defines schemas and contracts only. No planning or reasoning logic is implemented here.  

✅ 1.3.1. Plan Schema  
✅ 1.3.2. Local Planner  
✅ 1.3.3. Plan Validation  
✅ 1.3.4. Skill Metadata  
✅ 1.3.5. Skill Filtering  
✅ 1.3.6. Skill Ranking  
✅ 1.3.7. Executor Contract  
✅ 1.3.8. Single-Skill Execution     
✅ 1.3.9. Error Types  
✅ 1.3.10. Error Recovery Semantics  
✅ 1.3.11. CoreStep Pipeline  
✅ 1.3.12. Logging  
✅ 1.3.13. Unit Tests  
✅ 1.3.14. Integration Tests  

---

### PHASE 1.4 — Error Model, Retries, Resilience
*Depends On*: PHASE 1.3

✅ 1.4.1. Define error taxonomy — LLMError, ToolError, ValidationError, SystemError.  
✅ 1.4.2. Implement retry policy — per error type.  
✅ 1.4.3. Add LLM retry wrapper — transient network/timeouts.  
✅ 1.4.4. Add tool retry wrapper — idempotent tools only.  
✅ 1.4.5. Add circuit breaker per tool — stop repeated failures.  
✅ 1.4.6. Add degraded mode — fallback to simpler behaviour.      
✅ 1.4.7. Add safe failure response — structured error.  
✅ 1.4.8. Add panic guard — catch unexpected exceptions.  
✅ 1.4.9. Add loop self‑healing — adjust state, continue.  
✅ 1.4.10. Detect poison jobs — mark unrecoverable inputs.  
✅ 1.4.11. CLI helper that prints the plan (python3 main.  py agent plan)  
✅ 1.4.12. Bug fixes leading to stable Release 0   

### PHASE 1.5 - STRATUM 1 Invariant Checker
*Depends On*: PHASE 1.4  
✅ 1.5.1 — File System & Import Graph Scanner  
✅ 1.5.2 — Rule Engine Framework  
✅ 1.5.3 — Stratum Boundary Enforcement Rules  
✅ 1.5.4 — Execution Purity Rules (S1 Constraints)  
✅ 1.5.5 — Type & Schema Invariant Checks  
✅ 1.5.6 — Substrate Purity Checks  
✅ 1.5.7 — CLI Tool  
✅ 1.5.8 — Reporter & Output System  
1.5.9 — Deployment Gate Integration (optional github action workflow)  

---
🚀 Release 0 — "The Substrate"
---

### PHASE 1.6 — Provider Integrations (ChatProvider implementations)
*Depends On*: PHASE 1.5  

[untested]✅ 1.6.1. Anthropic (Claude) provider  
[untested]✅ 1.6.2. OpenAI provider  
✅ 1.6.3. Google (Gemini) provider  
[untested]✅ 1.6.4. Mistral provider  
[untested]✅ 1.6.5. Alibaba (Qwen) provider  

### PHASE 1.7 - Dead-code Analyser
*Depends On*: None

✅ 1.7.1 Dead-code analyser

## STRATUM 2 - Hierarchical Intelligence
*Invariant*: Stratum 2 must be pure: no side effects, no tool calls, no LLM calls. It only produces subgoals and plan segments for Stratum 1 to execute.  

### PHASE 2.1 - Multi-Step Loop Foundation
*Depends on*: PHASE 1.4  

✅ 2.1.1 — Step State
- Define StepState model — fields, lifecycle, immutability rules  
- Implement StepState transitions — pending → running → done → error  
- Add StepState validation — ensure shape, required fields  

✅ 2.1.2 — Step Result
- Define StepResult schema — success, failure, tool_needed, continue  
- Implement StepResult factory — helpers for each result type  
- Add StepResult validators — ensure consistency  

✅ 2.1.3 — CoreStep v2 
- Implement CoreStep lifecycle — init → run → classify → output  
- Implement CoreStep error handling — integrate substrate error envelope  
- Implement CoreStep transitions — deterministic state machine  
- Integrate OutcomeClassifier — call classifier, map to StepResult

*Note*: CoreStep v2 must operate only on provided cognitive inputs; all LLM calls are delegated to Stratum 1

✅ 2.1.4 — Loop Policy
- Define LoopPolicy model — max steps, timeouts, retry budget  
- Implement LoopPolicy enforcement — stop conditions  
- Add LoopPolicy metrics — counters, durations  

✅ 2.1.5 — Step Outcome Classifier
- Define classifier prompt  
- Implement classifier wrapper  
- Add classifier validation  
*Note*: Classifer wrapper must not call the LLM; it only interprets classifier outputs provided by Stratum 1

✅ 2.1.6 — Loop Orchestrator 
- Implement LoopController — deterministic loop engine  
- Implement LoopTermination logic — stop, continue, error  
- Add LoopOrchestrator metrics — step count, durations

✅ 2.1.7 - Determinism rules
- Define invariants that guarantee identical cognitive inputs always produce identical outputs
- Specify canonical ordering, stable hashing, strict immutability of StepState/StepResult
- Add deterministic tie-breaking rules for ambiguous classification or transitions

✅ 2.1.8 - Cognitive contract
- Define the interface between Stratum 1 and Stratum 2: what Stratum 2 receives (state, last result, memory) and what it must return (subgoal, segment, plan, or classification)
- Specify allowed input/output shapes and error semantics
- Ensure the contract is pure: no side effects, no execution, no tool selection

✅ 2.1.9 - Cognitive trace
- Define a structured trace object capturing *why* each cognitive decision was made
- Record: chosen transitions, rejected alternatives, drift signals, validation outcomes
- Ensure the trace is append-only, immutable, and serialisable for debugging

✅ 2.1.10 — Subgoal/Segment State
- Extend ConversationState  
- Add SubgoalState model  
- Add SegmentState model  

✅ 2.1.11 - Purity Enforcement Layer
- Validate no tool calls
- Validate no LLM calls
- Validate no side effects
- Validate immutability of cognitive inputs
- Validate determinstic outputs

✅ 2.1.12 - Cognitive Normalisation Layer
- Stable ordering of inputs
- Stable hashing of cognitive state
- Canonical normalisation of cognitive structures

### PHASE 2.2 - Flat Planner (non-hierarchical)
*Depends on*: PHASE 2.1  

✅ 2.2.1 — Plan Generator
- Define plan generation prompt  
- Implement PlanGenerator wrapper  
- Add plan generation validators  
*Note*: PlanGenerator produces a prompt template only; Stratum 1 performs the actual LLM call

✅ 2.2.2 — Plan Validator
- Define Plan schema  
- Implement PlanValidator rules — safety, allowed actions  
- Add PlanValidator error reporting  

✅ 2.2.3 — Plan Executor
- Implement StepDispatcher — run each step via CoreStep  
- Implement PlanError propagation — map step errors → plan errors  
- Add PlanExecutor metrics  

✅ 2.2.4 — Plan State
- Define PlanState model  
- Implement PlanState transitions  
- Add PlanState validators  

✅ 2.2.5 — Plan Execution Safety Layer
- Define safety rules that prevent invalid or dangerous plan execution
- Wrap StepDispatcher with pre-execution checks and post-execution validation
- Implement safety checks — forbidden actions, invalid transitions 
- Add safety logging  

✅ 2.2.6 — Planning Composition (Initial Wiring)
- Expose substrate components (PlanGenerator, PlanValidator, PlanExecutor, SafeStepDispatcher)  
- Provide a minimal composition root for internal testing  
- Do not integrate into the agent loop yet  
- Ensure all components are import‑stable for Phase 2.3  


### PHASE 2.3 - Hierarchical planning
*Depends On*: PHASE 2.2  

✅ 2.3.1 — Subgoal Model
- Define Subgoal schema  
- Add Subgoal validators  

✅ 2.3.2 — PlanSegment Model
- Define PlanSegment schema  
- Add PlanSegment validators  

✅ 2.3.3 — Subgoal Manager
- Implement Subgoal creation  
- Implement Subgoal validation  
- Implement Subgoal transitions  

✅ 2.3.4 — Plan Manager
- Implement Segment creation  
- Implement Segment stitching  
- Implement Segment validation  

✅ 2.3.5 — Governed Signals (Merged with Drift Signals)
- Define governed signals: drift, stuck, unsafe  
- Implement signal emitters  
- Implement drift thresholds and drift classification  
- Provide unified signal interface for 2.5.x  

✅ 2.3.6 — Agent‑Level Loop Skeleton (Initial Wiring)
- Assemble minimal agent loop using substrate components  
- Integrate SafeStepDispatcher (first real wiring)  
- Add basic reflection hooks (no memory yet)  
- Add minimal error handling  

✅ 2.3.6a - Janitor cleanup
- cleanup drift
- remove duplication
- restructure
- creation of a /tools/architecture/ci_architecture_check.py analyser which creates a /docs/architecture.json file which is a breakdown of packages, classes, references, and an architecture_audit.md, which is an analysis of deadcode, class duplication, drift, architecture and invariant violations, and finally, a prioritised list of issues. This is designed to fail if at least one critical or high priority issue exists.

✅ 2.3.7 — Subgoal Transition Rules
- Define transition rules  
- Implement transition engine  

✅ 2.3.8 — Drift Detection (Refined)
- Implement multi‑signal drift detection using governed signals  
- Add drift recovery hooks  
- Add drift confidence scoring  

✅ 2.3.9 — Subgoal Validation Rules
- Define validation rules  
- Implement validation engine      

### PHASE 2.4 - Memory Model v1
*Depends On*: PHASE 2.3  

✅ 2.4.1 — Subgoal Memory
- Implement SubgoalMemory store  
- Add SubgoalMemory retrieval  

✅ 2.4.2 — Segment Memory
- Implement SegmentMemory store  
- Add SegmentMemory retrieval  

✅ 2.4.3 — Plan Memory
- Implement PlanMemory store  
- Add PlanMemory retrieval  

✅ 2.4.4 — Drift Memory
- Implement DriftMemory store  
- Add DriftMemory retrieval

✅ 2.4.5 - Memory governance  

✅ 2.4.6 - Summarisation rules  

✅ 2.4.7 - Memory eviction rules
- LRU or LFU
- Drift-triggered eviction
- Subgoal completion eviction
- Summarised-state replacement

## PHASE 2.5 Full Hierarchical Reasoner
*Depends On*: PHASE 2.4  
*Note*: builds on skeleton iterations above to complete Stratum 2

✅ 2.5.1 — Plan Repair
- Implement full repair logic: detect broken plans, identify minimal fixes, regenerate segments, or re‑decompose subgoals  
- Integrate memory, governed signals, and validation rules  
- Add repair budget + retry limits

✅ 2.5.2 - Full transition rules
- Expand the skeleton rules into a complete transition graph covering all subgoal and segment states
- Add edge cases, fallback paths, and error transitions

✅ 2.5.3 - Full drift detection
- Implement multi-signal drift detection combining behavioural, structural, and temporal signals
- Add confidence scoring and multi-step drift confirmation

✅ 2.5.4 - Full validation rules
- Integrate all validation layers: subgoal, segment, plan, memory and safety
- Ensure validation is deterministic and composable

✅ 2.5.5 - Reflection Loop
- Implement a full reflection cycle: evaluate progress, detect drift, refine subgoals, adjust plans, and update memory
- Ensure reflection is pure and deterministic

✅ 2.5.6 — Agent‑Level Loop v2 (Full Implementation)
- Implement the complete agent loop: hierarchical reasoning, reflection, memory integration, and governed transitions  
- Add full error handling, fallback strategies, and trace generation  
- Final wiring of all substrate + safety + memory components 

✅ 2.5.7 - inspection dashboard
- TUI-bsaed dashboard for inspecting agent planning behaviour

✅ 2.5.8 - Mock LLM
- Bridge end-to-end planning pipeline
- Attach a Mock LLM to create scenarios for testing

## PHASE 2.6 — Stratum‑2 Behavioural Engine (Executor‑Aware Reasoner)
*Depends On*: PHASE 2.5  
*Goal*: Give Stratum‑2 the ability to observe, interpret, and reason about actual execution behaviour.

✅ 2.6.1 — Capability Execution Model
- Define deterministic capability outputs for S2 observation  
- Add capability metadata: purity, determinism, expected shape  
- Add execution‑shape validator (expected vs actual)

✅ 2.6.2 — Behavioural Observation Layer
- Capture executor outputs into SegmentState  
- Add behavioural deltas (prevoutput → newoutput)  
- Add behavioural anomaly detector (wrong shape, wrong type)

✅ 2.6.3 — Behavioural Drift Signals
- Emit signals for:  
  - wrong capability  
  - wrong output shape  
  - wrong output semantics  
  - unexpected side‑effects (detected via metadata)

✅ 2.6.4 — Behavioural Drift Classifier
- Map signals → drift classification  
- Add confidence scoring  
- Add multi‑cycle confirmation

✅ 2.6.5 — Behavioural Repair Actions
- Fix wrong capability  
- Fix malformed step  
- Regenerate segment  
- Regenerate plan (if needed)

✅ 2.6.6 — Behavioural Trace
- Add behavioural deltas to trace  
- Add drift signals to trace  
- Add repair actions to trace

## PHASE 2.7 — Temporal Reasoner (Progress, Stalls, Recovery)
*Depends On*: PHASE 2.6  
*Goal*: Give Stratum‑2 a sense of time, progress, and stagnation.

✅ 2.7.1 — Progress Detector
- Compare segment outputs across cycles  
- Detect: steady, stalled, regressed  
- Add progress confidence scoring

✅ 2.7.2 — Temporal Drift Signals
- Emit signals for:  
  - no progress  
  - repeated identical outputs  
  - oscillation  
  - regressions

✅ 2.7.3 — Temporal Drift Classifier
- Multi‑cycle stall detection  
- Oscillation detection  
- Regressed‑state detection

✅ 2.7.4 — Temporal Repair Actions
- Regenerate segment  
- Regenerate plan  
- Re‑decompose subgoal  
- Reset segment state

✅ 2.7.5 — Temporal Trace
-  Add progress deltas  
-  Add stall reasons  
-  Add oscillation markers

## PHASE 2.8 — Semantic Reasoner (Meaning, Intent, Goal Alignment)
*Depends On*: PHASE 2.7  
*Goal*: Give Stratum‑2 the ability to detect when behaviour contradicts the plan or subgoal.

✅ 2.8.1 — Semantic Validator
- Validate output against step description  
- Validate output against plan intent  
- Validate output against subgoal goal  
- Validate output against memory context

✅ 2.8.2 — Semantic Drift Signals
- Emit signals for:  
  - contradicting plan  
  - contradicting subgoal  
  - contradicting memory  
  - contradicting prior behaviour

✅ 2.8.3 — Semantic Drift Classifier
- Multi‑signal semantic drift detection  
- Confidence scoring  
- Confirmation logic

✅ 2.8.4 — Semantic Repair Actions 
- Rewrite step  
- Rewrite segment  
- Rewrite plan  
- Rewrite subgoal

✅ 2.8.5 — Semantic Trace
- Add semantic mismatch details  
- Add semantic repair actions  
- Add semantic drift history

## PHASE 2.9 — Full Drift Engine (Unified Drift System)
*Depends On*: PHASE 2.8  
*Goal*: Combine behavioural, temporal, and semantic drift into a unified, governed system.

✅ 2.9.1 — Unified Drift Signal Model
- Merge structural, behavioural, temporal, semantic signals  
- Add signal weighting  
- Add signal decay rules

✅ 2.9.2 — Unified Drift Classifier
- Multi‑signal classification  
- Confidence scoring  
- Drift severity levels  
- Drift categories: minor, major, catastrophic

✅ 2.9.3 — Drift Confirmation Engine
- Multi‑cycle confirmation  
- Confidence accumulation  
- Drift hysteresis (avoid oscillation)

✅ 2.9.4 — Drift Recovery Engine
- Choose repair vs replan  
- Choose segment regen vs plan regen  
- Choose subgoal regen vs full reset

✅ 2.9.5 — Drift Trace
- Add unified drift history  
- Add drift confidence evolution  
- Add drift recovery decisions

## PHASE 2.10 — Full Repair Engine (Beyond Normalisation)
*Depends On*: PHASE 2.9  
*Goal*: Implement real repair actions, not just structural fixes.

✅ 2.10.1 — Repair Action Library
- Fix malformed steps  
- Fix malformed segments  
- Fix malformed plans  
- Fix malformed subgoals  
- Fix drift‑induced inconsistencies

✅ 2.10.2 — Repair Budget
- Per‑cycle budget  
- Per‑subgoal budget  
- Per‑plan budget  
- Global budget

✅ 2.10.3a — Repair Arbitration
- Decide between:  
  - repair  
  - replan  
  - regenerate segment  
  - regenerate subgoal  
  - escalate to catastrophic drift

✅ 2.10.3b - Testing harness  
  - signal_harness (tools/testing_harness/signal_harness.py)  
  - plan_repair_harness (tools/testing_harness/plan_repair_harness.py)  

✅ 2.10.4 — Repair Trace
- Add repair attempts  
- Add repair failures  
- Add repair successes  
- Add repair budget usage

## PHASE 2.11 — Multi‑Segment Reasoner
*Depends On*: PHASE 2.10  
*Goal*: Execute multi‑segment plans with drift/repair/reflection per segment.

✅ 2.11.1 — Segment Transition Rules
- pending → active  
- active → complete  
- complete → next segment  
- complete → subgoal complete

✅ 2.11.2 — Segment Reflection
- Evaluate progress  
- Evaluate drift  
- Evaluate repair  
- Evaluate completion

✅ 2.11.3 — Segment‑Level Drift
- Drift per segment  
- Repair per segment  
- Replan per segment

✅ 2.11.4 — Segment Trace
- Add segment transitions  
- Add segment drift  
- Add segment repair  
- Add segment reflection

## PHASE 2.12 — Multi‑Subgoal Reasoner
*Depends On*: PHASE 2.11  
*Goal*: Execute hierarchical plans with multiple subgoals.

✅ 2.12.1 — Subgoal Transition Rules
- pending → active  
- active → complete  
- complete → next subgoal  
- complete → agent complete

✅ 2.12.2 — Subgoal Reflection
- Evaluate subgoal progress  
- Evaluate subgoal drift  
- Evaluate subgoal repair  
- Evaluate subgoal completion

✅ 2.12.3 — Subgoal‑Level Drift
- Drift per subgoal  
- Repair per subgoal  
- Replan per subgoal

✅ 2.12.4 — Subgoal Trace
- Add subgoal transitions  
- Add subgoal drift  
- Add subgoal repair  
- Add subgoal reflection

## PHASE 2.13 — Full Agent‑Level Loop v3 (Release‑Ready)
*Depends On*: PHASE 2.12  
*Goal*: The complete hierarchical reasoner required for Stratum‑3.

✅ 2.13.1 — Full Agent Loop
- Multi‑subgoal  
- Multi‑segment  
- Multi‑cycle  
- Drift‑aware  
- Repair‑aware  
- Reflection‑aware  
- Memory‑aware

✅ 2.13.2 — Full Error Handling
- catastrophic drift  
- catastrophic repair failure  
- invalid memory state  
- invalid subgoal state  
- invalid segment state

✅ 2.13.3 — Full Trace
- agent trace  
- subgoal trace  
- segment trace  
- drift trace  
- repair trace  
- reflection trace  
- memory trace

✅ 2.13.4 — Release 0.1 Validation
- determinism tests  
- drift tests  
- repair tests  
- multi‑segment tests  
- multi‑subgoal tests  
- long‑horizon tests 

## PHASE 2.14 — Stratum 2 Closure & S1 Integration

✅ 2.14.1 — S2/S1 Contract Hardening
Define the exact boundary between S2 and S1.
- S1 request schema
- S1 response schema
- Tool call schema
- Error schema

✅ 2.14.2 — S1 Adapter Layer
Introduce a thin, deterministic adapter layer:
- s2_to_s1_adapter
- s1_to_s2_adapter
This ensures:
- S2 never calls the LLM directly  
- S2 never sees raw strings  
- S1 never sees internal S2 structures  
Adapters are pure functions.  
No side effects.

✅ 2.14.3 — Deterministic S1 Simulation Backend
Preserve the current deterministic world as a first‑class mode.
- backend="simulation"  
- backend="real_llm"
Simulation backend provides:
- deterministic drift  
- deterministic repair  
- deterministic reflection  
- deterministic plan shaping  

✅ 2.14.4 — Prompt Shaping & Response Validation
Make the LLM safe.
- strict JSON‑only prompts
- schema‑guided instructions
- invalid response handling

If the LLM returns garbage:
- S2 does not crash  
- S2 does not drift  
- S2 does not mutate state  
- S2 surfaces a structured AgentError  

✅ 2.14.5 — End‑to‑End S1+S2 Smoke Tests
Run tiny plans through the full stack:
- 1 subgoal, 1 segment  
- 1 subgoal, 3 segments  
- 2 subgoals, 2 segments each  

Run each with:
- backend="simulation"  
- backend="real_llm"

Assertions:
- no crashes  
- trace is valid  
- errors are structured  
- S2 state machine behaves identically where possible  

✅ 2.14.6 — LLM‑On Readiness Checklist 
A binary checklist for flipping the switch:  
- [x] All 2.13.x tests green  
- [x] All critical/high architecture issues resolved  
- [x] S2/S1 contract locked  
- [x] Simulation backend stable  
- [x] Real LLM backend wired behind a flag  
- [x] Invalid S1 response handling tested  
- [x] E2E smoke tests pass  
- [x] Architecture audit clean for S2/S1 boundary  

✅ 2.14.7 — Actual Integration to S1 (Live LLM Enablement)  
1. Implement the real S1 client  
- call_llm(request)  
- Uses your chosen provider (OpenAI, Azure, local model, etc.)  
- Handles:  
  - retries    
  - timeouts    
  - rate limits    
  - streaming (if you choose)    
2. Wire S2 to use the real client  
- Replace all stubbed S1 calls with real S1 client when backend == "real_llm"    
3. Add safety wrappers  
- Validate JSON    
- Validate schema    
- Validate required fields    
- On failure:  
  - return AgentError(type="invalids1response")  
  - do not mutate S2 state  
4. Add a “LLM‑on” smoke test  
- Run a tiny plan    
- Confirm:  
  - no crashes    
  - trace is valid    
  - S2 state machine stays intact    
5. Add a kill‑switch
- A simple config flag: `enable_real_llm = false`  

✅ 2.14.8 — Testing LLM Integration  
1. Smoke testing  
- Minimal S1→LLM→S1 round‑trip    
- Tiny S2 plan test   
2. Developer tooling    
- Manual cycle runner    
3. Statistical conformance runner    
- scenario‑agnostic probabilistic test harness  
- Metric extractors  
- Scenario JSON definitions    
- Aggregator, thresholds evaluator, CLI entry point (`python -m tests.statistical.cli`)  
4. Integration verified    
- DeepSeek v4 Flash (default) and v4 Pro both produce schema‑valid PromptResponse  
- Kill‑switch (`ENABLE_REAL_LLM`) honoured at all entry points  
- No S2 state mutation on invalid S1 responses  
- All manual tests pass against live LLM  

### PHASE 2.15 — Planner Contract Hardening
Depends On: PHASE 2.4, PHASE 2.8, PHASE 2.13

Goal: Formalise and freeze the planning and execution contracts used by S2, S3, and future S4 workers. No new planning logic — this is schema hardening and boundary definition.

✅ 2.15.1 — AgentPlan schema (versioned)
Define a stable, versioned schema for full plans:
- subgoals  
- segments  
- expected outputs  
- failure modes  
- metadata  

✅ 2.15.2 — StepSpec schema (versioned)
Define deterministic step contract:
- intent  
- args  
- expected_output  
- target_skill (optional)  
- fallback strategies (optional)  

✅ 2.15.3 — Unified planning entrypoint
Expose AgentPlanner.plan(goal) that:
- calls SubgoalPlanner  
- calls PlanGenerator  
- validates via PlanValidator  
- returns a complete AgentPlan  

✅ 2.15.4 — Freeze S2→S3 execution contract
Stabilise and version:
- SkillCallRequest  
- SkillResult  
- segment execution metadata  

(This already exists in S3Adapter; this phase freezes it.)

✅ 2.15.5 — Tests
- multi‑subgoal plan shapes  
- multi‑segment plan shapes  
- contract stability across versions  

### PHASE 2.16 — Semantic Memory v2
Depends On: PHASE 2.4, PHASE 2.8, PHASE 2.15, PHASE 3.19

Goal: Introduce meaning‑aware memory structures that improve planning, repair, and reflection.  
S2 remains pure — embeddings are computed in S3 and provided to S2.

✅ 2.16.1 — Semantic memory record schema
Extend memory records with:
- topics  
- entities  
- capability patterns  
- embedding vectors (precomputed by S3)  
- outcome classification  

✅ 2.16.2 — SemanticMemoryIndex (pure S2)
Implement a deterministic index supporting:
- similar subgoal lookup  
- similar drift lookup  
- similar capability‑chain lookup  
- historical outcome retrieval  

✅ 2.16.3 — Memory‑aware planning
PlanGenerator consults SemanticMemoryIndex to:
- bias toward historically successful strategies  
- avoid drift‑prone patterns  
- apply deterministic scoring  

✅ 2.16.4 — Memory‑aware repair
Repair engine consults SemanticMemoryIndex to:
- prefer historically successful repair actions  
- avoid repeated failures  

✅ 2.16.5 — Tests
- deterministic semantic lookup  
- memory‑aware plan shaping  
- memory‑aware repair selection  

### PHASE 2.17 — Repair Learning Layer
Depends On: PHASE 2.10, PHASE 2.16

Goal: Move from reactive repair to adaptive repair.  
S2 learns from past repair outcomes using deterministic rules.  
**Scope guard**: Counterfactual and pattern recognition use only deterministic frequency‑based rules (e.g., action X succeeded ≥80% → promote; action Y failed ≥3× → demote). No LLM reasoning. If deterministic rules prove insufficient, defer 2.17.3‑4 to a future phase.

✅ 2.17.1 — RepairMemory store
Record:
- drift type  
- chosen repair action  
- outcome  
- cost  
- recurrence  

✅ 2.17.2 — RepairPolicy engine
Deterministic policy:
- choose repair actions based on historical success  
- avoid actions with repeated failures  
- respect repair budgets  

✅ 2.17.3 — Counterfactual repair (deterministic only)
Record alternative actions when repair fails:
- alternative skills  
- alternative segment shapes  
- alternative decompositions  
Apply frequency‑based scoring — no LLM reasoning.

✅ 2.17.4 — Pattern recognition (deterministic only)
Detect repeated drift → repeated fix → stable policy:
- promote successful patterns (≥80% success rate)  
- demote failing patterns (≥3 consecutive failures)  
All thresholds determined by frequency counts, not semantic analysis.

✅ 2.17.5 — Tests
- repair policy determinism  
- repair outcome learning  
- counterfactual correctness

### PHASE 2.18 — Release 0.1 Integration & Hardening
Depends On: PHASE 2.15, PHASE 2.16, PHASE 2.17

Goal: Wire all S2 components end‑to‑end, freeze the Release 0.1 surface area, and validate against live LLM + S3 adapter before declaring Release 0.1.

✅ 2.18.1 — Integration test suite
- Full plan‑execute‑repair loop across multi‑subgoal prompts  
- Cross‑component boundary validation (Planner → Executor → Repair)  
- Deterministic replay tests (record‑and‑replay for known goals)  

✅ 2.18.2 — Contract freeze
- Lock AgentPlan / StepSpec schema versions at v1.0  
- Lock S2→S3 execution contract at v1.0  
- Document all frozen contracts in `docs/contracts/`  

✅ 2.18.3 — Performance baseline
- Measure end‑to‑end latency for representative multi‑step plans  
- Establish SLOs: plan generation < Tₚ, execution < Tₑ, repair < Tᵣ  
- No optimisation — just measurement  

✅ 2.18.4 — Release 0.1 sign‑off checklist
- All S2 contract tests pass  
- All S2 integration tests pass  
- All manual LLM tests pass (3 representative prompts, documented)  
- `ENABLE_REAL_LLM` kill‑switch honoured at all entry points  
- No regressions in S1 or S3 pipeline  

✅ 2.18.5 — Final S2 bug sweep
- Triage all remaining S2 TODO/FIXME comments (zero found)  
- Close all S2‑specific Medium/Low audit issues  
- Canonical loaders created in ``src/capabilities/primitives/stdlib/__init__.py`` and ``src/capabilities/skills/stdlib/__init__.py``  
- Invariant checker passes against all strata  

✅ 2.18.6 — REPL test harness
- Stdin loop that accepts user prompts, returns a plan, remembers conversation context  
- Drives end‑to‑end integration testing across the full S2 pipeline  
- Validates plan‑execute‑repair loop with real LLM interactions  
- Serves as the primary manual testing interface for Release 0.1→1.0  
- Two-phase output: Phase 1 (Plan creation + diagnostics) → Phase 2 (Skill execution results)  
- Supports ``--mock`` (MockLLM) and ``--no-execute`` (plan‑only) flags  

---

🚀 Release 0.1 — "Hierarchical Reasoner"
---

## STRATUM 3 - Agent Runtime
*Invariant*: Stratum 3 orchestrates agents, capabilities and external interfaces, but never performs long-horizon reasoning, planning, and execution itself. It delegates all reasoning to Stratum 2 and all action execution to Stratum 1.

**Isolation rule**: All S3 code lives under `src/capabilities/` — completely isolated from S1 (`src/core/`) and S2 (`src/stratum2/`). S3 defines its own contracts using only standard Python types and never imports S1/S2 internals. Integration occurs via a thin adapter in S2's runtime that speaks S3's public contract.

---

### PHASE 3.0 — Foundations: Specs, Contracts, and Directory Layout
*Depends On*: PHASE 2.14.8

✅ 3.0.1 — Folder layout
- Create `src/capabilities/` with sub-packages:
  ```
  src/capabilities/
    __init__.py
    contracts.py            # S2↔S3 boundary types
    primitives/
      __init__.py
      base.py               # PrimitiveBase, PrimitiveResult
      python.py             # PythonPrimitive
      cli.py                # CLIPrimitive
      mcp.py                # MCPPrimitive
    registry/
      __init__.py
      primitive_registry.py
      loaders/
        __init__.py
        python_loader.py
        cli_loader.py
        mcp_loader.py
        plugin_loader.py 
    skills/
      __init__.py
      manifest.py           # .skill.md parser
      skill.py              # Skill dataclass
      executor.py           # Step interpreter
    discovery/
      __init__.py
      embedder.py
      search.py
    stdlib/
      __init__.py
      primitives/           # Built-in primitives live here
      skills/               # Built-in .skill.md files live here
    runtime/
      __init__.py
      skill_runner.py       # Entry point for S2→S3 calls
  ```

✅ 3.0.2 — Primitive metadata spec
- Define the shape of a primitive: name, type (`python` | `cli` | `mcp`), function signature, description, declared side effects, input/output schema

✅ 3.0.3 — Skill manifest spec (`.skill.md`)
- YAML front matter: `skill`, `description`, `primitives` (list of names), `inputs` (schema), `steps` (ordered list of `call:` references)
- Markdown body: human-readable description and usage notes

✅ 3.0.4 — S2↔S3 boundary contracts
- `SkillCallRequest`, `SkillResult`, `SkillDiscoveryQuery`, `SkillDiscoveryResult` as pure dataclasses in `src/capabilities/contracts.py`
- No imports from `src/core/` or `src/runtime/`

---

### PHASE 3.1 — Primitive Abstraction Layer
*Depends On*: PHASE 3.0

A single interface for all primitive types (Python, CLI, MCP) with deterministic execution semantics.

✅ 3.1.1 — PrimitiveBase
- Abstract base class with unified signature: `execute(args: dict, context: dict) → PrimitiveResult`

✅ 3.1.2 — PrimitiveResult
- Dataclass: `status` (success | error), `data`, `error` (message string), `side_effects` (list of observed effects)

✅ 3.1.3 — PythonPrimitive
- Wraps a Python callable with signature validation and side-effect tracking

✅ 3.1.4 — CLIPrimitive
- Wraps a CLI command string; subprocess execution with stdout/stderr capture and exit-code handling

✅ 3.1.5 — MCPPrimitive
- Wraps an MCP tool reference; delegates to MCP client for execution

✅ 3.1.6 — Tests
- Each primitive type: valid args, invalid args, side-effect tracking, error propagation

---

### PHASE 3.2 — Primitive Registration & Discovery
*Depends On*: PHASE 3.1

A registry that loads primitives from code, CLI definitions, MCP manifests, and plugins. Vector-based semantic discovery.

✅ 3.2.1 — PrimitiveRegistry
- `register(name, primitive)`, `get(name) → PrimitiveBase`, `list(filter) → list`, `find(query) → list[Match]`

✅ 3.2.2 — Python loader
- Scans Python modules for `PrimitiveBase` subclasses, auto-registers by name

✅ 3.2.3 — CLI loader
- Reads CLI definition files (JSON/YAML), instantiates `CLIPrimitive` instances

✅ 3.2.4 — MCP loader
- Reads MCP server manifests, instantiates `MCPPrimitive` instances

✅ 3.2.5 — Embedding-based discovery
- Generate embeddings from primitive name + description + signature; cosine-similarity search via `registry.find("resize an image")`

✅ 3.2.6 — Plugin loader stub
- Placeholder for Phase 3.14; directory scanned but empty initially

✅ 3.2.7 — Tests
- Registration, duplicate handling, name collisions, discovery relevance ranking, loader edge cases

---

### PHASE 3.3 — Skills: Declarative Capability Layer
*Depends On*: PHASE 3.2

Skills are declarative `.skill.md` files with YAML front matter. S2 can call skills deterministically.

✅ 3.3.1 — `.skill.md` parser
- Extract YAML front matter, validate required fields, resolve primitive references against registry

✅ 3.3.2 — SkillManifest dataclass
- `name`, `description`, `primitives` (list of primitive names), `inputs` (schema dict), `steps` (ordered list of `{call, args, on_error}`)

✅ 3.3.3 — Skill dataclass
- Manifest + resolved `PrimitiveBase` objects + validated input/output schemas

✅ 3.3.4 — SkillExecutor
- Interpret steps sequentially: resolve primitive by name → call `primitive.execute(args, context)` → collect results → return `SkillResult`

✅ 3.3.5 — Validation
- At parse time: all referenced primitives exist; input schema is well-formed; step ordering is valid
- At execution time: args match input schema; all steps complete or error

✅ 3.3.6 — Tests
- Parse valid `.skill.md`, reject malformed front matter, execute skill with mock primitives, test error propagation from failed primitives

---

### PHASE 3.4 — Skill Registration & Semantic Discovery
*Depends On*: PHASE 3.3

Skills are discoverable via embeddings and ranked by relevance. S2 can select skills during planning.

✅ 3.4.1 — SkillRegistry
- `register(skill)`, `get(name) → Skill`, `list(filter) → list`, `find(query) → list[Match]`

✅ 3.4.2 — Skill embedding generation
- Embed skill name + description + step descriptions for semantic search

✅ 3.4.3 — Semantic skill search
- `find(query)` returns skills ranked by cosine similarity to query embedding

✅ 3.4.4 — Skill metadata validation
- At registration time: validate primitive references resolve, input schemas are consistent, no circular skill references

✅ 3.4.5 — Tests
- Registration, discovery relevance ranking, same-query consistency, validation rejection of broken skills

---

### PHASE 3.5 — Skill & Primitive Metadata Export
*Depends On*: PHASE 3.4

S3 exposes static, declarative metadata so S2 can make deterministic planning decisions without violating purity.

✅ 3.5.1 — Metadata fields on primitives and skills
- Capability cost (latency, resource usage)
- Determinism (pure, impure, nondeterministic)
- Side-effects (fs, network, dangerous)
- Expected output shape (schema, types)
- Failure modes (TimeoutError, HTTPError, etc.)
- Safety level (low, medium, high)
- Prerequisites (domain policy, auth, environment)

✅ 3.5.2 — Metadata export via SkillDiscoveryResult
- S3 attaches metadata to every discovered skill and primitive
- Metadata is versioned and stable across releases

✅ 3.5.3 — S2 consumption points
- Metadata consumed during skill discovery, plan generation, segment construction
- Also used for repair decisions, drift detection, and reflection

✅ 3.5.4 — Tests
- Deterministic ordering and hashing of exported metadata
- Metadata stability across registry rebuilds

---

### PHASE 3.6 — Structured Skill Discoverability
*Depends On*: PHASE 3.5

Extends SkillManifest with metadata fields for deterministic, ranked skill discovery.

✅ 3.6.1 — SkillManifest metadata fields
- Capability tags (e.g., "fetch", "parse", "transform")
- Input/output types, side-effect class, safety level
- Cost estimate, determinism level
- Prerequisites (domain policy, auth)

✅ 3.6.2 — Deterministic discovery ranking
- Rank by: exact tag match → schema compatibility → safety level → determinism → cost → embedding similarity
- Ensures S2 picks the same skill every time for a given query

✅ 3.6.3 — Skill discovery families
- Group skills into families: fetch.*, file.*, parse.*, transform.*, browser.*
- Helps S2 reason about alternatives during planning

✅ 3.6.4 — Tests
- Ranking determinism across repeated queries
- Family grouping correctness

---

### PHASE 3.7 — Standard Library Core v1 (stdlib MVP)
*Depends On*: PHASE 3.4

A minimal but powerful stdlib of primitives and skills to bootstrap the agent.

✅ 3.7.1 — `echo` primitive
- Returns input unchanged; used as canary for the full S2→S3→S2 round-trip

✅ 3.7.2 — `file.read` primitive
- Reads file at path, returns content as string

✅ 3.7.3 — `file.write` primitive
- Writes content to file at path

✅ 3.7.4 — `proc.exec` primitive
- Executes shell command via subprocess, returns stdout/stderr/exit_code

✅ 3.7.5 — `echo` skill
- `.skill.md` wrapping `echo` primitive; validates input schema

✅ 3.7.6 — `json.parse` skill
- Parses JSON string via `echo` → Python parsing; returns dict or error

✅ 3.7.7 — `fetch.simple` skill (stub)
- Declares `net.httpget` dependency; stub implementation until Phase 3.10

✅ 3.7.8 — Tests
- Each stdlib primitive and skill executed end-to-end via SkillExecutor

---

### PHASE 3.8 — S2 ↔ S3 Integration (Thin Adapter + Bug Fixes) — 9/10 complete
*Depends On*: PHASE 3.7
*Design rule*: S3 (`src/capabilities/`) never imports S1/S2. Integration code lives in `src/stratum2/s3_adapter.py` as an adapter that speaks S3's public contract.
*Note*: All S3 components (contracts, SkillRunner, SkillExecutor, S3Adapter) are built and tested via 26 integration tests. PlanExecutor is now wired into AgentLoopV2's main cycle via step 4.6 (3.8.10 ✅).

✅ 3.8.1 — Finalize boundary contracts
- `SkillCallRequest`, `SkillResult`, `SkillDiscoveryQuery`, `SkillDiscoveryResult`, `DiscoveredSkill` as pure dataclasses in `src/capabilities/contracts.py`

✅ 3.8.2 — Fix `SkillRunner` bugs + add `discover()`
- **BUG**: Line 31 uses class `CapabilitySkillRegistry` instead of instance `CapabilitySkillRegistry()` — `self._registry.get()` will raise `TypeError` at runtime
- Fix the instantiation bug
- Add `discover(query, limit) → SkillDiscoveryResult` method wrapping registry's `find()`
- Unit tests for both paths

✅ 3.8.3 — SkillExecutor template variable interpolation (**CRITICAL: resolves current {{ value }} literal-passing**)
- The `SkillExecutor.execute()` passes step-args literally (e.g. `{"value": "{{ value }}"}`) to primitives
- Implement a lightweight `_interpolate_args(args, inputs)` step that resolves `{{ key }}` tokens against user-supplied inputs before calling `primitive.execute()`
- Must support nested templates in string values within `args`
- Must not use Jinja2/Mustache — implement a simple regex-based resolver (`re.sub(r'\{\{\s*(\w+)\s*\}', ...)`)
- Must be deterministic, pure, and side-effect-free
- Update skill tests to interpolate args instead of asserting literal `{{ value }}`

✅ 3.8.4 — `SkillExecutor` inline Python step support
- The `json.parse` skill has a `- python: |` block that `SkillExecutor` does not currently support
- Implement Python block execution: detect `python` key in step (vs `call`), execute via `exec()` or inline, return dict as primitive result
- Must be deterministic, sandboxed, and clean up local namespace

✅ 3.8.5 — S3 adapter in S2 runtime
- `src/stratum2/s3_adapter.py`: `discover_skills(query)`, `call_skill(request)`, handles contract translation S2-native ↔ S3 contract types
- This is the ONLY file that imports from both S2 and S3

✅ 3.8.6 — Wire skill discovery into S2 planning
- S2 queries S3 for relevant skills during plan construction; skill names stored in plan segments

✅ 3.8.7 — Wire skill execution into S2 cycle
- Segment referencing a skill triggers `s3_adapter.call_skill()` during cycle execution

✅ 3.8.8 — Wire skill results into S2 state
- `SkillResult` → S2 state update → segment memory record

✅ 3.8.9 — Tests
- S2→S3→S2 round-trip with e.g. `stdlib.echo` skill: subgoal → segment → skill call → result → state update
- Template interpolation correctness: `{{ value }}` resolves to actual user input
- Python step execution via SkillExecutor
- Error propagation: invalid skill name, failed execution
- Discovery flow: S2 queries skills, receives ranked list

✅ 3.8.10 — Wire PlanExecutor into the agent cycle (**DONE — AgentLoopV2 step 4.6**)
- `AgentLoopV2` seeds plans via `SubgoalPlanner.plan_for_subgoal()` (step 4.5) and now dispatches them through `PlanExecutor` in step 4.6 before reflection runs.
- `PlanExecutor.execute()` calls `S3Adapter.call_skill()`, writes `SegmentMemoryRecord` — invoked from the agent loop as an optional injection.
- **Re-dispatch guard**: Step 4.6 checks `SegmentMemoryRecord` existence for `plan.targetskillid` before dispatching (PlanExecutor writes one on first successful execution), preventing duplicate skill calls across cycles.
- `AgentLoopV2.__init__()` accepts optional `plan_executor: Optional[PlanExecutor] = None`.  Pass it from `planning_composition.py` (which already constructs it).

---

### PHASE 3.9 — Tiny S3 Smoke Test
*Depends On*: PHASE 3.8

A minimal end-to-end test against the real LLM that proves S2 can discover and call an S3 skill. Pattern mirrors Phase 2.14.7's smoke test.

✅ 3.9.1 — `tests/manual/test_s3_smoke.py`
- 1 subgoal, 1 segment calling `stdlib.echo` via `backend=real_llm`

✅ 3.9.2 — Verify skill discovery
- S2 queries S3 for relevant skills; `stdlib.echo` appears in results

✅ 3.9.3 — Verify plan construction
- S2 builds a plan with a segment that references `stdlib.echo`

✅ 3.9.4 — Verify skill execution
- S3 executes `stdlib.echo` via SkillExecutor; result returned to S2

✅ 3.9.5 — Verify state update
- S2 updates segment memory from `SkillResult`

✅ 3.9.6 — Verify trace completeness
- Trace contains: skill discovery query → discovery result → skill call → skill result → state update

✅ 3.9.7 — Real LLM confirmation
- Run with `--backend real_llm`; confirm the full S2→S3→S2 circuit works end-to-end

✅ 3.9.8 — Statistical conformance
- Run `python -m tests.statistical.cli --scenario tiny_s3_smoke --repetitions 25 --backend real_llm`; verify 100% json_validity, 100% schema_validity, 0 catastrophic failures

✅ 3.9.9 — AgentLoopV2 full-cycle smoke
- Inject PlanExecutor into AgentLoopV2, run one cycle, verify: plan seeded (step 4.5), dispatched (step 4.6) → SegmentMemoryRecord written, reflection ran (step 5), no errors.

---

### PHASE 3.10 — Fetch Orchestrator: Simple HTTP
*Depends On*: PHASE 3.7

✅ 3.10.1 — FetchError taxonomy
- Dataclasses: `TimeoutError`, `HTTPError` (status_code, body), `ParseError`, `ConnectionError`

✅ 3.10.2 — `stdlib.http.simple` primitive
- httpx GET with configurable timeout, headers, status-code handling
- Returns: `status_code`, `body` (str), `headers` (dict), `elapsed` (ms)

✅ 3.10.3 — `fetch_url` skill
- Wires to `http.fetch` primitive; returns status + body + headers
- Accepts `url` and optional `timeout`, `headers` args

✅ 3.10.4 — Tests
- Successful fetch, timeout, 4xx response, 5xx response, connection refused, invalid URL

✅ 3.10.5 - FetchRequest, FetchResponse objects

Purpose:
Provide consistent, chainable request/response objects that allow the fallback router to:
- inspect responses
- classify signals
- retry with modified requests
- propagate cookies/headers
- maintain a trace of attempts

Requirements:
- collect request and response data, which will allow subsequent fetches to honour headers, cookies, etc
- ensure any fallback actions propagate these objects
- hydrate_next_request() method
- JSON-serialisable shapes for LLM inspection
- Integration with http.fetch primitive
- Integration with fetch_url skill

✅ 3.10.6 - Test Harness
- Allow fetch to be executed independently
- Allow user to inject websites that are use-cases for things like simple fetch, hardened fetch, javascript, SPA, anti-bot, etc
- This test harness will be used to define fetch hardness as we iterate

---

### PHASE 3.11 — Fetch Orchestrator: Hardened Modes
*Depends On*: PHASE 3.10

✅ 3.11.1 — Hardened HTTP fetch mode
- Anti-bot headers (rotating User-Agent, Accept-Language), retry with exponential backoff, cookie jar

✅ 3.11.2 — Playwright headless fetch mode
- JS rendering via Playwright; handles SPA and JS-dependent content

✅ 3.11.3 — Playwright stealth fetch mode
- Stealth plugin, human-like timing, rate limiting, fingerprint masking

✅ 3.11.4 — Tests
- Each mode exercised against a known endpoint; mode-selection by flag; fallback on mode failure

---

### PHASE 3.12 — Fetch Orchestrator: Escalation & Domain Policy
*Depends On*: PHASE 3.11

✅ 3.12.1 — Fetch heuristics
- Select initial mode based on URL pattern, content-type hints, prior success/failure history

✅ 3.12.2 — Fallback chain
- `simple → hardened → browser → stealth → search`; each step triggered by `FetchError` type
- Mode-specific timeouts: simple (10s), hardened (15s), browser (30s), stealth (45s)

✅ 3.12.3 — Per-domain policy
- Allowlists, deny lists, rate limits, mode preferences per domain
- Configurable via `domain_policy.json` or equivalent

✅ 3.12.4 — Signals Taxonomy & Extraction
- JavaScript / Rendering Signals
- Anti‑Bot / Security Signals
- Content‑Type Signals
- Network / Protocol Signals
- Quality / Structure Signals

✅ 3.12.5 — Signal‑Driven Fallback Router

- Hard failures
- JavaScript / Rendering Signals
- Anti‑Bot Signals
- Content‑Type Signals
- Domain Policy Overrides
- Exhaustion

✅ 3.12.6 — Single LLM-facing interface
- Expose only `fetch_url` skill; internal strategies (modes, escalation, policy) hidden behind it
- LLM sees `fetch_url(url)` — nothing else

✅ 3.12.7 - Internal Mode and Metadata Sanitisation
- Ensure no internal fetch strategy, fallback step, signal, domain policy, or orchestrator meta is ever expose to the LLM

✅ 3.12.8 — Test Suite Specification
- Comprehensive test suite spec at `src/core/types/fetch/test_suite_3_12_8.json` (44 test cases)
- Covers: escalation triggers (6 error types × 5 mode transitions), signal-driven fallback (12 signals), domain policy enforcement (5 rules), request hydration (5 rules), sanitisation layer (6 leakage checks), timeout rules (6 modes), search fallback (3 scenarios), final response validation (5 cases)
- Test harness integration deferred to 3.18.3

---

### PHASE 3.13 — Search Provider
*Depends On*: PHASE 3.12  
This phase introduces a provider‑agnostic search layer.  
The runtime configures the provider (Tavily, Bing, SerpAPI, custom, etc.) and supplies API keys + parameters.  
The LLM does not know or care which provider is used.

✅ 3.13.1 — Search Provider Configuration
Define a runtime‑side configuration object:

- provider name (e.g., "tavily", "bing", "serpapi", "custom")  
- API key  
- endpoint override (optional)  
- provider‑specific parameters (optional)  
- max results defaults  
- rate limits (optional)

This is stored in the runtime, not the LLM.  
The LLM receives only the normalized output, never the API key.

---

✅ 3.13.2 — Search Primitive (Provider‑Agnostic)
Implements:

- Query → provider request → provider response → normalized results  
- Uses http_simple internally  
- Injects API key + provider params from configuration  
- Normalizes all providers into a single schema:

`
[
  { url, title, snippet },
  ...
]
`

The primitive does not perform fallback, heuristics, or ranking.

---

✅ 3.13.3 — search_urls Skill
Thin wrapper around the search primitive.

Responsibilities:

- Accepts { query, max_results }  
- Calls the search primitive  
- Returns normalized list of URLs with titles + snippets  
- No provider logic  
- No fallback logic  
- No heuristics  
- Implement two concrete providers as a test: DuckDuckGo (free) and Tabivily (requires api key)
---

✅ 3.13.4 — Integrate Search Into Fetch Fallback
When all fetch modes fail (simple → hardened → headless → stealth):

- The fallback router calls search_urls  
- Receives a list of alternative URLs  
- Attempts fetch again using the unified http_fetch orchestrator  
- Uses taxonomy (3.13.5) to choose the best fetch mode for each URL

Search is last‑resort, not a primary fetch strategy.

---

✅ 3.13.5 — GetPageFromUrl Taxonomy
Define a lightweight content‑type classifier:

- article  
- documentation  
- blog  
- unknown  

Used by fallback to choose:

- simple fetch  
- hardened fetch  
- headless fetch  
- stealth fetch  

This is provider‑agnostic.

---

✅ 3.13.6 — Tests
Verify:

- Provider configuration is respected  
- API key injection works  
- Search primitive returns normalized results  
- search_urls skill wraps correctly  
- Fallback router triggers search when all fetch modes fail  
- Search results are usable by downstream fetch  
- Taxonomy correctly classifies URLs  

---

### PHASE 3.14 — Plugin System
*Depends On*: PHASE 3.7

Users can drop in new primitives and skills with no code changes. Hot-loadable.

✅ 3.14.1 — Plugin manifest format
- `plugin.yml`: name, version, primitives (list), skills (list), dependencies

✅ 3.14.2 — Plugin loader
- Scans plugin directories, loads manifests, registers primitives + skills into registries

✅ 3.14.3 — Hot-reload
- Detect new/removed/modified plugins on file system changes; reload without restart

✅ 3.14.4 — Plugin authoring guide
- Document plugin structure, manifest schema, and examples in `docs/`
- Update documentation with plugin loader usage

✅ 3.14.5 — Tests
- Load plugin, execute plugin skill, unload/reload cycle, invalid manifest rejection, version conflict handling

---

### PHASE 3.15 — Deterministic Plugin Hot-Reload
*Depends On*: PHASE 3.14

Versioned, stable registries ensure hot-reloading plugins does not violate S2's determinism invariants.

✅ 3.15.1 — Stable registry ordering
- Sort by skill name → version → plugin name
- Guarantees deterministic iteration order across reloads

✅ 3.15.2 — Stable embedding IDs
- Hash of skill name + version + manifest hash
- Embedding IDs remain stable across reloads

✅ 3.15.3 — Registry snapshots
- On plugin change: compute new snapshot, freeze it, expose snapshot ID to S2
- S2 uses snapshot ID for deterministic planning

✅ 3.15.4 — Hot-reload flow
- Load plugin → rebuild registry → compute snapshot → freeze → notify S2
- S2 can continue with old snapshot or switch at a safe boundary

✅ 3.15.5 — Tests
- Same plugin set produces identical snapshot IDs
- Snapshot stability across registry rebuilds
- S2 snapshot selection and boundary switching

---

### PHASE 3.16 — Agent-Authored Skills (Future)
*Depends On*: PHASE 3.9

The agent can author new `.skill.md` files, propose new primitives, and extend its own capability layer.

✅ 3.16.1 — Skill authoring pipeline
- LLM writes `.skill.md` content; submitted to registry via validation gate

✅ 3.16.2 — Safety checks
- Validate all referenced primitives exist; input schemas are safe; no privilege escalation patterns
- Reject skills that reference disallowed primitives or attempt to override system skills

✅ 3.16.3 — Validation + embedding update
- Validated skills are registered and embedded; immediately discoverable by future S2 planning

✅ 3.16.4 — Tests
- Agent authors a valid skill, exercises it; validation rejects dangerous skills; authored skill appears in discovery results

---

### PHASE 3.17 — Agent-Authored Skill Safety Layer
*Depends On*: PHASE 3.16

Layered safety gates for agent-authored skills: structural, semantic, behavioural, and governance.

✅ 3.17.1 — Structural safety
- Validates: no recursive skill references, no unbounded loops, no dynamic primitive selection
- Extends existing primitive-existence, schema, and privilege-escalation checks

✅ 3.17.2 — Semantic safety
- Validator checks: skill description matches behaviour, no domain-policy bypass
- Also checks: no chaining of high-risk primitives, no embedded user code

✅ 3.17.3 — Behavioural safety
- Run authored skill in sandbox with mock primitives and side-effect tracking
- Reject on unexpected side-effects

✅ 3.17.4 — Governance
- Skill provenance (author, timestamp), versioning, optional signing
- Quarantine until validated; approval workflow

✅ 3.17.5 — Tests
- Validator rejects recursive references, policy bypass, high-risk primitive chains
- Sandbox captures unexpected side-effects
- Quarantine/approval workflow exercised

---

### PHASE 3.18 — Standard Library v2 (Full stdlib)
*Depends On*: PHASE 3.7

Expands the MVP stdlib to a comprehensive, well-organised standard library across ten capability families.

✅ 3.18.1 — Ultra-Low-Level File Primitives
- `file.read`, `file.readhead`, `file.readtail`, `file.readrange`
- `file.exists`, `file.list`, `file.search`, `file.glob`, `file.stat`
- `file.write`, `file.append`, `file.delete`

✅ 3.18.2 — Structured Data Primitives
- `json.parse`, `json.get`, `json.set`
- `yaml.parse`, `toml.parse`
- `markdown.parse`, `html.parse`, `html.select`, `pdf.extracttext`
- `csv.read`, `csv.write`

✅ 3.18.3 — Test Harness & Schema Injection
- `tools/testing_harness/run_cycle.py` — single-cycle architecture verifier (moved from root)
- `tools/testing_harness/e2e_harness.py` — end-to-end Prompt → LLM → Planner → Skills pipeline
- Wires: PrimitiveRegistry (63 primitives) → CapabilitySkillRegistry (61 skills) → SkillRunner → S3Adapter → SubgoalPlanner
- Backends: `--backend mock` (MockLLM) for plumbing tests, `--backend real_llm` (deepseek-chat) for live E2E
- Validates: skill discovery (semantic embedding search), plan generation (intent + target skill + steps), skill execution via SkillRunner
- Schema injection: skill input schemas flow S3→S2→planner automatically. `_build_system_prompt()` injects top-10 discovered skills with their input schemas. LLM correctly names skills (`stdlib.echo`) and populates per-step `inputs` (e.g., `{"value": "hello world"}`).
- `_describe_schema()` handles both JSON Schema format and flat manifest format (`{"param": {"type": "str", "required": true}}`).
- `targetskillid` priority: LLM step capability drives execution; discovery is a semantic hint.
- Mock backend: 2/2 steps execute with correct per-step inputs. Real LLM: correctly plans and executes `stdlib.echo`, `stdlib.net.ping` (host/port inferred), multi-step plans with distinct per-step inputs.
- Known: `json.parse.skill.md` fails to load (inline Python step); `search.web.skill.md` fails (unknown primitive). Optional parameters with template defaults (e.g., ping `timeout`) cause interpolation failures when LLM omits them — pre-existing skill template issue.

✅ 3.18.3b — Harness Hardening
- **Defaults audit:** Scanned all 63 skill manifests. Zero vulnerable manifests found — all `required: false` params in `{{key}}` templates have `default:` values. No fixes needed.
- **Planner prompt hardening:** Expanded planner prompt in `subgoal_planner.py` with 3 additional rules: (1) explicit cross-step reference example with `{{key}}` format, (2) never use `{{step-N}}` pattern, (3) use descriptive step IDs. Previously already had prohibition against `$.steps[N]` JSONPath and `{"$ref": "..."}` objects.
- **Whole-step reference resolution:** Added `{{step-N}}` fallback in all three template resolvers — `executor.py` (`_interpolate_args`), `repl_harness.py` (`_resolve_step_templates`), and `e2e_harness.py` (`_resolve_templates`). When a `{{step-N}}` token is matched and the key isn't found in resolved inputs, the fallback returns `json.dumps(resolved_inputs)`. Additionally, both harnesses now store `step-{i+1}` → `json.dumps(output)` in accumulated outputs after each step executes.
- **Re-test:** All 4659 tests pass, 2 skipped (pre-existing), 0 critical/0 high architecture issues.

✅ 3.18.4 — Database Primitives (Safe CRUD)
- `db.connect`, `db.query`, `db.insert`, `db.update`, `db.delete`
- `db.listtables`, `db.describetable`

✅ 3.18.5 — Network Primitives
- `net.httpget`, `net.httppost`, `net.dnslookup`, `net.ping`, `net.tcpcheck`

✅ 3.18.6 — Web Interaction Primitives
- `fetch.simple`, `fetch.hardened`, `fetch.browser`, `fetch.stealth`
- `search.web`

✅ 3.18.7 — Text & Document Processing
- `text.split`, `text.join`, `text.replace`, `text.extract`, `text.normalize`
- `doc.detecttype`, `doc.extractmetadata`

✅ 3.18.8 — System & Environment Primitives
- `sys.envget`, `sys.envlist`, `sys.timenow`, `sys.uuid`, `sys.tempfile`

✅ 3.18.9 — Process & Execution Primitives
- `proc.exec`, `proc.execsafe`, `proc.kill`, `proc.ps`
- (Optional; many runtimes omit for safety.)

✅ 3.18.10 — Compression & Encoding
- `zip.extract`, `zip.create`, `gzip.compress`, `gzip.decompress`
- `base64.encode`, `base64.decode`

✅ 3.18.11 — Tests
- Each primitive exercised end-to-end via SkillExecutor
- Category-level conformance suites (file, data, network, web, text, db, sys, proc, compression)

---

### PHASE 3.19 — Semantic Embeddings & Vector Search
*Depends On*: PHASE 3.4

Skills are currently discovered via a character-bucket hash (`_simple_embedding_fn`) which produces non‑semantic embeddings. The top‑ranked skill is essentially random. This phase replaces the character‑bucket hash with a proper embedding model and pre‑computed vector store, so that S2 discovery and S3 skill selection return semantically meaningful results.

✅ 3.19.1 — Real embedding function
- Integrate `EmbeddingGenerator` with a real semantic embedding provider, but only for discovery fallback, not for primary skill selection.
Responsibilities:
- Replace the dummy vector generator with a real embedding model (Open AI text-embedding-3-small-bge-small-en, or MiniLM-L6-v2)
- Wrap the embedding model behind a provider-agnostic interface
- Add a query embedding cache (per session) to avoid recomputing embeddings during retries, re-planning or fallback
- Add a skill embedding generator that produces embeddings from skill name, description, step summaries, signature
- Precompute and store skill embeddings at registration time
- Store embeddings inside the skill registry entry (no re-embedding per query)
- Keep _simple_embedding_fn for deterministic unit tests
- Use real embeddings only for integration/E2E tests
Constraints:
- Embeddings are used only for discovery fallback, never for execution
- LLM-chosen skills always take precedence
- Embedding provider must be pluggable (OpenAI, local model, mock)
- No network calls in unit tests

✅ 3.19.2 — Pre‑computed skill embeddings
- Generate and persist embeddings at skill registration time (name + description + step summaries).
- Store in registry alongside the `CapabilitySkill` object — no re‑embedding per query.
- Rebuild embeddings on skill hot‑reload (tie into PHASE 3.14/3.15).

✅ 3.19.3 — Vector similarity search
- Cosine similarity over pre‑computed embeddings.
- Return top‑K skills with similarity scores.
- Replace the current `registry.find()` character‑bucket path with the real vector path.

✅ 3.19.4 — Embedding cache & provider abstraction
- Cache query embeddings per session to avoid redundant API calls.
- Abstract embedding provider behind a configurable interface (OpenAI, local model, mock).
- Provider selection via environment variable or config file.

✅ 3.19.5 - Discovery Fallback Wiring
- Modify planner to trust LLM-named skill first
- Modify planner to only invoke semantic search when the LLM fails
Add a fallback path:
- LLM produces a plan
- Extract named capabilities
- Validate capability existence
- if missing -> run semantic search
- select top-1 match
- insert into the execution plan

✅ 3.19.6 — Tests
- Embedding determinism: same text → same vector.
- Semantic relevance: "list files" ranks `stdlib.file.list` above `stdlib.json.set`.
- Cache hit/miss and API failure fallback.
- Registry rebuild preserves embeddings across hot‑reload.
- Fallback wiring tests (`test_fallback.py`): 15 tests, all passing.

### PHASE 3.19.7 — Remaining test gaps  
*Depends On*: PHASE 3.19.6

✅ HIGH
- [x] Vector store count assertion after N skill registrations.
- [x] Hot‑reload e2e test — re‑embed a skill, call `find_semantic`, verify updated results.

✅ MEDIUM
- [x] Real provider `embed()` call test (integration scope).
- [x] `config.yaml` → `EmbeddingConfig` parse chain test.
- [x] Cache isolation test — two `SkillEmbedder` instances with independent caches.
- [x] Cache‑under‑provider‑error test — verify cache survives embedding provider failure.

✅ LOW
- [x] Invalid `EmbeddingConfig` error handling test.
- [x] `find_semantic` exact k boundary test (k=1, k=0, k > available).

### PHASE 3.20 — Episode Continuity (S2 Logic)
*Depends On*: PHASE 2.16, PHASE 2.17, PHASE 3.19  
(Moved out of Release 0.1 — requires 2.16 and 2.17 completion.)

Goal: Provide continuity across episodes within a session using the semantic memory and repair learning systems already built in S2. This phase is pure S2 logic with no cross‑stratum dependencies.

✅ 3.20.1 — ProjectMemory
Store:
- recurring goals  
- preferred skills  
- known bad patterns  
- domain policies  

✅ 3.20.2 — UserProfile memory
Store:
- preferences  
- constraints  
- behavioural patterns  

✅ 3.20.3 — Episode boundaries
Define:
- episode start  
- episode end  
- summarisation  
- compaction  

✅ 3.20.4 — Tests
- episode summarisation  
- project‑scoped memory retrieval  
- cross‑episode plan shaping  

> **Deferred to S4/S5**: Persistence (previously 3.20.4) and identity integration (previously 3.20.5) are scoped to future S4 and S5 phases when those strata are built. See PHASE 4.x (Continuity Persistence) and PHASE 5.x (Identity & Persona Integration).

## PHASE 3.21 - Refinement

✅ 3.21.1 — Primitive Error Taxonomy

Hierarchy (src/core/types/errors/primitive_errors.py):
Execution: 
- PrimitiveExecutionError (generic catch-all, retryable=caller),
- PrimitiveTimeout (retryable)
- PrimitiveRetryableError (transient, retryable),
- PrimitiveNonRetryableError (deterministic failure), 
- PrimitiveSideEffectError (unexpected mutation → abort+escalate)

Validation: 
- PrimitiveValidationError (schema mismatch → replan),
- PrimitiveContractError (pre/post-condition violation → replan or escalate)

Privilege & Safety: 
- PrimitivePrivilegeError (unauthorised op → abort+escalate)

Environment & Dependency: 
- PrimitiveEnvironmentError (missing config → escalate),
- PrimitiveDependencyError (upstream failure, retryable)
- PrimitiveNotFound (registry miss → semantic search + replan)

All 11 types inherit PrimitiveError(AgentError, Exception) — raisable, planner-compatible, LLM-parsable.
map_error_to_recovery() extended: retryable types → RETRY, validation/contract/not-found → REPLAN,
side-effect/privilege/environment → ESCALATE. retryable flag on every error; subclasses set safe defaults,
callers may override.

✅ 3.21.2 - Skill Execution Semantics
Defined 
- `SkillExecutionContract` (frozen dataclass) with: `timeout_seconds`, `cancellable`
- `SkillRetryPolicy` (max_attempts, backoff_factor, retryable_error_types) 
- `atomicity` (best_effort / checkpoint / all_or_nothing)
- `SkillCompensationStep` (undo steps for all-or-nothing)
- `SkillSideEffectBudget` (max_mutations / file_writes / network_calls), `step_failure_policy`, `allow_parallel_steps`, `allow_step_skip` Added `from_dict()` for manifest round-tripping
Wired `execution_contract` field into `CapabilitySkill` and `SkillManifest.from_dict()`

✅ 3.21.3 - Planner Error Semantics
Defined 
- `PlannerError(AgentError, Exception)` base + 6 subtypes: `PlanInvalid` (→ REPLAN) 
- `PlanAmbiguous` (→ CLARIFY)
- `PlanMissingCapabilities` (→ REPLAN, carries `missing_capabilities` tuple)
- `PlanUnsafe` (→ ESCALATE, carries `violated_rule`)
- `PlanExecutionFailed` (→ RETRY if retryable else REPLAN, carries `failed_step`)
- `PlanDegraded` (→ RETRY, carries `fallback_used`)
Extended `map_error_to_recovery()` with `_map_planner_error()`
Exported `ALL_PLANNER_ERROR_TYPES`

✅ 3.21.4 - Capability Graph Consistency
`CapabilityGraphChecker` (pure read-only): `check_dangling_primitives()`, `check_dangling_skills(referenced)`, `check_schema_drift(baseline_primitives)`, `check_privilege_drift(baseline_privileges)`, `check_capability_cycles()` (DFS on skill→skill deps), `check_plugin_unload_safety(plugin_name)`. Returns `GraphConsistencyReport` (frozen, `is_clean`, `violations_by_kind()`). `ConsistencyViolation` frozen dataclass with 6 kind constants.
---

🚀 Release 0.2 — "Extensible Agent"
---

## REFACTOR - Reduce tech debt, enforce domain->stratum mapping, remove medium/low issues

Refactor.1 - New folder structure
  /src/runtime (s1 concerns)
  /src/strategy (s2 concerns)
  /src/capabilities (s3 concerns)
  /src/platform (s4 concerns)
  /src/agent (s5 concerns)

Refactor.2 - Remove test warnings
Refactor.3 - Remove Medium, Low issues
Refactor.4 - Cleanup documentation (readme, contributing, roadmap, tools, architecture)

---
🚀 Release 1.0 - Basic Agent
---

## STRATUM 4 — Distributed Runtime & System Infrastructure

### PHASE 4.1 — FastAPI Ingress Layer
The ingress layer becomes the single entry point for all external traffic.
- FastAPI Gateway — request parsing, routing, session context  
- Transport abstraction — unify HTTP, WS, CLI, webhook  
- Authentication — API keys, tokens, service accounts  
- Rate limiting — per‑user, per‑IP, per‑channel  
- Ingress request envelope — normalize all inbound messages  
- Ingress → Control Plane handoff  

Outcome:  
A stable, typed, authenticated gateway that feeds all work into the system.

---

### PHASE 4.2 — Queueing Layer & Job Model
This is the backbone of Stratum 4: durable, observable, priority‑aware job orchestration.

- Queue abstraction — Redis, SQS, or your own  
- Job envelope — metadata, retries, deadlines, priority  
- Priority queues — high/medium/low lanes  
- DLQ — poison message handling  
- Queue metrics — depth, throughput, latency  
- Queue managers — balancing, draining, pausing  

Outcome:  
A durable, observable job pipeline that can feed workers at scale.

---

### PHASE 4.3 — Worker Pool & Execution Layer
Workers become isolated, supervised, cancellable execution units.

- Worker pool — concurrency, scaling  
- Worker supervisors — crash detection, restart policy  
- Circuit breakers — isolate failing primitives  
- Job cancellation — cooperative cancellation  
- Timeouts — per‑job and per‑primitive  
- Heavy workers — browser automation, long‑running tasks  
- Worker metrics — CPU, memory, queue lag  

Outcome:  
A resilient execution layer capable of running light and heavy tasks safely.

---

### PHASE 4.4 — Control Plane
This is the “brain” of Stratum 4 — the orchestrator of orchestrators.

- Task ledger — durable record of all jobs  
- State machine — pending → running → success/failure  
- Synchronization — locks, leases, coordination  
- Backpressure — slow workers → slow ingress  
- Scheduling decisions — which worker gets which job  
- Retry policy — exponential backoff, jitter  
- Control plane API — inspect, cancel, reprioritize  

Outcome:  
A central orchestrator that manages job lifecycle, scheduling, and system health.

---

### PHASE 4.5 — Lifecycle Management
This is where tasks become first‑class citizens with full lifecycle semantics.

- Lifecycle hooks — before/after/cleanup  
- Checkpoints — resumable tasks  
- Hydration/dehydration — long‑running workflows  
- Idempotency — safe retries  
- Task cancellation — propagate signals to workers  

Outcome:  
Tasks become durable, resumable, and safely retryable.

---

### PHASE 4.6 — Transport Layer
Unifies all inbound/outbound communication channels.

- HTTP transport  
- WebSocket transport  
- CLI transport  
- Webhook transport  
- Transport envelope — unify message format  
- Channel routing — map channels → workflows  

Outcome:  
A unified transport abstraction that supports multi‑channel agents.

---

### PHASE 4.7 — Heartbeat & System Health
This is the “vital signs” layer.

- Heartbeat daemon — periodic system pings  
- Worker heartbeat — detect dead workers  
- Queue heartbeat — detect stuck queues  
- Health checks — liveness, readiness, startup  
- Alerting hooks — Slack, email, PagerDuty  

Outcome:  
A self‑monitoring system that detects failures before users do.

---

### PHASE 4.8 — Security & Governance
The guardrails that make Stratum 4 production‑safe.

- AuthN/AuthZ — per‑channel, per‑user, per‑token  
- Rate limiting — global + per‑tenant  
- Audit logging — every job, every primitive  
- Secrets management — vault integration  
- Isolation — sandboxing heavy tasks  
- **Cross‑channel notification dispatch** — quarantine awareness for IDE, web, CLI, Slack surfaces.  (Deferred from 3.17.4; currently operators must poll `quarantine_list_pending()` manually.)  

Outcome:  
A secure, multi‑tenant‑capable runtime.

---
🚀 Release 6 — "Multi-Agent System"
---

## STRATUM 5 - Agent Runtime (Above CoreStep)
*Invariant*: Orchestrates agents, memory, identity, multi-agent systems.  

### PHASE 5.1 — Agent Runtime Core
*Depends On*: PHASE 4.3

5.1.1. Define AgentSpec — instructions, tools, loop policy.  
5.1.2. Implement agent registry  
5.1.3. Implement agent context — memory, settings.  
5.1.4. Implement agentstep — inject instructions.  
5.1.5. Implement agentloop — wraps CoreStep.  
5.1.6. Add agent permissions  
5.1.7. Add agent templates  
5.1.8. Add multi‑agent orchestration  
5.1.9. Add scheduled agents  
5.1.10. Add agent debugging view
5.1.11. Agent Memory Model
5.1.12. Agent Identity & Persona Model
5.1.13. Agent Capability Graph

---

### PHASE 5.2 — Resilience, Self‑Healing, Health
*Depends On*: PHASE 5.1

5.2.1. Classify loop health — healthy, stalled, poisoned.  
5.2.2. Detect stalled loops  
5.2.3. Auto‑abort stalled loops  
5.2.4. Auto‑downgrade behaviour  
5.2.5. Add global watchdog  
5.2.6. Add auto‑scaling hooks  
5.2.7. Add panic reporting  
5.2.8. Add resilience tests  
5.2.9. Add recovery drills  
5.2.10. Document failure modes

---
🚀 Release 7 — "Production-Ready Runtime"
---

### PHASE 5.3 — Observability & Developer Experience
*Depends On*: PHASE 5.2

5.3.1. Add structured logging  
5.3.2. Add metrics exporter  
5.3.3. Add tracing spans  
5.3.4. Add flamegraph timings  
5.3.5. Add local dev CLI  
5.3.6. Add replay tooling  
5.3.7. Add config inspector  
5.3.8. Add skill inspector  
5.3.9. Add agent inspector  
5.3.10. Add end‑to‑end smoke tests

---
🚀 Release 8 — "Observable and Developer-Friendly Runtime"
---

### PHASE 5.4 — Hardening & Polish
*Depends On*: PHASE 5.3

5.4.1. Security review of skills  
5.4.2. Security review of fetch stack  
5.4.3. LLM prompt hardening  
5.4.4. Config profiles — dev, prod, paranoid.  
5.4.5. Backwards‑compatible APIs  
5.4.6. Performance tuning  
5.4.7. Load testing  
5.4.8. Graceful degradation strategy  
5.4.9. Disaster recovery story  
5.4d.10. Write architecture doc — for future contributors.

---
🚀 Release 9 — "Hardened Runtime"
---

## STRATUM 6 - Cognitive Systems and Meta-Agents
*Note*: Future considerations of what is possible, rather than on the roadmap

### PHASE 6.1 - Meta-Planning and Self-Reflection

### PHASE 6.2 - Long-Term Memory and Knowledge Graphs

### PHASE 6.3 - Multi-Agent Societies

### PHASE 6.4 - Tool Learning and Skill Synthesis

### PHASE 6.5 - Autonomy and Governance

---
