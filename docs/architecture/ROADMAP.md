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

**Isolation rule**: All S3 code lives under `src/capabilities/` — completely isolated from S1 (`src/runtime/`) and S2 (`src/strategy/`). S3 defines its own contracts using only standard Python types and never imports S1/S2 internals. Integration occurs via a thin adapter in S2's planning layer that speaks S3's public contract.

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
*Design rule*: S3 (`src/capabilities/`) never imports S1/S2. Integration code lives in `src/strategy/planning/adapters/s3_adapter.py` as an adapter that speaks S3's public contract.
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
- `src/strategy/planning/adapters/s3_adapter.py`: `discover_skills(query)`, `call_skill(request)`, handles contract translation S2-native ↔ S3 contract types
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
- `CapabilityGraphChecker` (pure read-only): `check_dangling_primitives()``check_dangling_skills(referenced)`, `check_schema_drift(baseline_primitives)`, `check_privilege_drift(baseline_privileges)`, `check_capability_cycles()` (DFS on skill→skill deps), `check_plugin_unload_safety(plugin_name)`. Returns `GraphConsistencyReport` (frozen, `is_clean`, `violations_by_kind()`). `ConsistencyViolation` frozen dataclass with 6 kind constants.


🚀 Release 0.2 — "Extensible Agent"
---

## REFACTOR - Reduce tech debt, enforce domain->stratum mapping, remove medium/low issues

✅ Refactor.1 - New folder structure  
  /src/runtime (s1 concerns)  
  /src/strategy (s2 concerns)  
  /src/capabilities (s3 concerns)  
  /src/platform (s4 concerns)  
  /src/agent (s5 concerns)  

✅ Refactor.2 - Remove test warnings  
✅ Refactor.3 - Reduce Medium, Low issues  
✅ Refactor.4 - Capability Loaders (CLILoader, MCPLoader)  
- Extend capability discovery beyond Python stdlib primitives to support CLI and MCP primitives  
  *(CLILoader wraps local CLI tools as CapabilityPrimitive instances; MCPLoader connects to MCP servers and
  exposes their tools/skills as CapabilityPrimitive instances. Both abstract the calling mechanism so that
  S3's skill executor can invoke any primitive (Python, CLI, or MCP) through a uniform interface.
  *Rationale*: These loaders were built alongside the existing PythonLoader but never wired into the
  capability registry. Wiring them unlocks CLI tool access and MCP server integration without requiring
  Python wrappers for each external tool)*

---
🚀 Release 1.0 - Basic Agent
---

## STRATUM 4 — Platform Runtime
*Invariants*: 
- S4 must remain operational, deterministic, isolated, and free of cognitive logic.  
- Platform stratum must be strictly isolated from other strata (S4 may orchestrate S1/S2/S3, but it must never reach into them)
- Components within S4 should be isolated from each other where possible (each S4 subsystem should be independently testable, replaceable, and composable)
- platform lives in /src/platform
- S4 orchestrates execution but never performs reasoning.  


## PHASE 4.1 — Minimal Execution Path (MVP Runtime)
Goal: Make the system run a single job end‑to‑end.

✅ 4.1.1 — Gateway (Transport Boundary)
- Define FastAPI app with a single POST /run endpoint.  
- Accept raw JSON payload → validate → hand to channel normalizer.  
- No channels, no WebSockets, no auth.

✅ 4.1.2 — Channel Normalization (ChannelMessage v1)
- Define ChannelMessage schema: {input, metadata, channel="cli"}.  
- Implement CLI → ChannelMessage converter.  
- Implement gateway → ChannelMessage converter.

✅ 4.1.3 — Job Envelope (Job v1)
- Define Job model: id, created_at, state, payload, result.  
- Implement job creation from ChannelMessage.

✅ 4.1.4 — In‑Memory Queue (Queue v1)
- Implement simple FIFO queue.  
- Push job into queue on /run.

✅ 4.1.5 — Minimal Worker Loop (Worker v1)
- Worker pops job → calls S1/S2/S3 adaptor → stores result.  
- No concurrency, no retries, no lifecycle.

✅ 4.1.6 — S1/S2/S3 Adaptor (Thin Boundary Layer)
- Implement s2tos1adapter and s1tos2adapter.  
- Ensure S4 never sees internal S2 structures.  
- Ensure S2 never sees raw LLM/tool outputs.

✅ 4.1.7 — Result Retrieval
- Add GET /jobs/{id} endpoint.  
- Return job result.

✅ 4.1.8 — Logging & Tracing
- Minimal logs: job created, job started, job finished.

✅ 4.1.9 - Test harness for s4 MVP
- keep extending this test harness to include changes every iteration
- include usage in /docs/architecture/TOOLS.md

Outcome:  
The system can run a single request → through S1/S2/S3 → return a result.

---

## PHASE 4.2 — Control Plane (State Machine v1)
Goal: Introduce job lifecycle, state transitions, and basic orchestration.

✅ 4.2.1 — Job State Machine
- pending → running → succeeded/failed.  
- Add state validation + transitions.

✅ 4.2.2 — Control Plane Manager
- Implement ControlPlane class to manage job lifecycle.  
- Add job registry + state updates.

✅ 4.2.3 — Error Handling v1
- Wrap worker execution in try/except.  
- Mark job as failed with structured error.

✅ 4.2.4 — Timeouts v1
- Add per‑job timeout.  
- Mark job as failed if exceeded.

✅ 4.2.5 — Control Plane Trace
- Append state transitions to job trace.

Outcome:  
Jobs now have lifecycle, state transitions, and structured failure.

---

## PHASE 4.3 — Lifecycle & Hydration (ExecutionContext v1)
Goal: Enable multi‑cycle execution (S2 reflection, drift, repair).

✅ 4.3.1 — ExecutionContext Model
- Define schema: cognitive state, last result, memory snapshot.  
- Add serialization + hydration.

✅ 4.3.2 — Checkpointing
- Store ExecutionContext after each cycle.  
- Worker loads context on resume.

✅ 4.3.3 — Resume Tokens
- Add resume token to job envelope.  
- Worker uses token to continue multi‑cycle execution.

✅ 4.3.4 — Multi‑Cycle Worker Loop
- Worker runs:  
  while not done: step → update context → checkpoint.

✅ 4.3.5 — Lifecycle Trace
- Add hydration/dehydration events to trace.

Outcome:  
The runtime can execute multi‑step S2 reasoning loops.

---

## PHASE 4.4 — Reliability & Safety (Retries, Backoff, Poison Jobs)
Goal: Make S4 robust under failure.

✅ 4.4.1 — Retry Policy
- Per‑error‑type retry rules.  
- Exponential backoff.

✅ 4.4.2 — Poison Job Detection
- Mark job as poison after N failures.  
- Move to dead‑letter queue.

✅ 4.4.3 — Worker Crash Recovery
- Worker restarts job from last checkpoint.  
- Ensure idempotency.

✅ 4.4.4 — Panic Guard
- Catch unexpected exceptions.  
- Mark job failed safely.

✅ 4.4.5 — Degraded Mode
- Fallback to simpler execution if S1/S2 unstable.
- ⚠️ Runtime semantics still a stub — safe fallback output format, escalation path, and recovery trigger deferred to S4.7.5.

✅ 4.4.6 — Worker Pipeline Abstraction
- Refactor process_next() into a composable stage pipeline.
- Each choke (crash recovery, poison, idempotency, degraded, retry, panic) becomes a PipelineStage with evaluate() → Decision.
- Preserves evaluation order invariant without procedural entanglement.
- Keeps the worker lean as S4.5–S4.8 add more stages.

✅ 4.4.7 — Subsystem Unit Tests
- Add parameterized unit tests for all 5 pure-logic evaluators:
  RetryPolicy, PoisonDetector, CrashRecovery, PanicGuard, DegradedMode.
- Harness remains the primary integration validation tool.
- Unit tests cover edge cases the harness doesn't (empty rules, boundary thresholds, token mismatches).

Outcome:  
S4 becomes resilient to errors, crashes, and malformed inputs.

---

## PHASE 4.5 — Concurrency & Worker Pool
Goal: Support multiple workers and parallel execution.

✅ 4.5.0 — Queue Backend Abstraction
- Define Queue interface (push, pop, acknowledge, requeue).
- Implement Redis List backend.
- In-memory queue from 4.1.4 becomes default for dev/testing.
- ⚠️ Required before 4.5.1 — in-memory queue doesn't survive multi-process.

✅ 4.5.1 — Worker Pool
- Implement N workers.  
- Configurable concurrency.

✅ 4.5.2 — Thread/Process Isolation
- Choose threads or processes.  
- Ensure S1/S2 purity preserved.

✅ 4.5.3 — Job Scheduling
- FIFO or priority queue.  
- Add scheduling policy.

✅ 4.5.4 — Worker Heartbeats
- Workers emit heartbeat events.  
- Control plane monitors health.

✅ 4.5.5 — Worker Crash Recovery
- Restart crashed workers.  
- Requeue in‑flight jobs.
- ⚠️ Complements 4.4.3 (job-level crash recovery). 4.4.3 resumes from checkpoint within a cycle; 4.5.5 restarts the worker process itself. 4.5.5 depends on 4.4.3's checkpoint metadata.

✅ 4.5.6 — Persistence Backend Abstraction
- Define JobStore interface (save, load, list, delete).
- Implement SQLite backend.
- In-memory JobStore from 4.1.x becomes default for dev/testing.
- ⚠️ Required before 4.9 production deployment.

Outcome:  
S4 can run many jobs concurrently and safely.

---

## PHASE 4.6 — Channels (CLI, Web, WebSocket, Webhooks)
Goal: Add multiple ingress channels without changing S1–S3.

✅ 4.6.1 — Channel Abstraction
- Define Channel interface:  
  receive(), normalize(), send().

✅ 4.6.2 — CLI Channel
- Local CLI → ChannelMessage.  
- TUI optional.

✅ 4.6.3 — Web Channel
- Web UI → FastAPI → ChannelMessage.

✅ 4.6.4 — WebSocket Channel
- Real‑time streaming updates.  
- Push job state changes.

✅ 4.6.5 — Webhook Channel
- Generic webhook adapter.  
- Normalizes inbound POSTs.

✅ 4.6.6 — Provider‑Specific Webhooks
- WhatsApp  
- Slack  
- GitHub  
- Jira  
(each isolated in its own folder)

Outcome:  
S4 can accept requests from any client or platform.

---

## PHASE 4.7 — Supervisors & Governance
Goal: Add system‑level monitoring and self‑healing.

✅ 4.7.0 — Degraded Mode Runtime Semantics
- Define what "safe fallback output" actually looks like (schema, content).
- Define escalation path: who gets notified, how to trigger recovery.
- Define recovery trigger: what events bring the worker back to normal mode.
- ⚠️ Stub from 4.4.5 needs real semantics before production.

✅ 4.7.1 — Supervisor Loop
- Monitor worker pool.  
- Restart unhealthy workers.

✅ 4.7.2 — Queue Supervisor
- Detect stuck jobs.  
- Detect queue backpressure.

✅ 4.7.3 — Control Plane Supervisor
- Detect inconsistent job states.  
- Auto‑repair or escalate.

✅ 4.7.4 — System‑Level Alerts
- Emit alerts to Slack/email.
- Structured alert payloads.
- Implementation: `src/platform/supervisor/system_alerts.py`
- ⚠️ Mail selected as default system-alert, with a devsmtp service used for testing 
- ⚠️ Opinionated selection for testing is currently MailHog, but that's easily swappable with an smtp service or smtp4dev, or slack


✅ 4.7.5 — Unified Instruction Dispatch
- Formalize how the daemon dispatches all instruction types:
  PanicInstruction, PoisonInstruction, RecoveryInstruction,
  DegradedInstruction, RetryInstruction.
- Each instruction maps to one action: fail, retry, recover, degrade, etc.
- Keeps the daemon generic — adding a new instruction in S4.9+ doesn't
  require daemon changes.

Outcome:
S4 becomes self‑healing and production‑ready.

---

✅ 4.7.6 — Real LLM Dispatch + Interactive Channels
- Replace `_mock_execute` in `src/platform/runtime/worker.py:43` with a
  real `ChatProvider.chat()` call that hits an actual LLM backend.
- Wire the existing `ChatProvider` protocol (`src/strategy/llm/providers/_base.py`)
  into the S4 worker's execution pipeline.
- Add `enable_real_llm` configuration switch to toggle mock ↔ real dispatch.
- Add prompt input to CLI channel: read stdin, submit as S4 job, display
  LLM response to stdout.
- Add prompt input to TUI channel: add an input widget to the operator
  console, submit prompt as S4 job, render LLM response in a dedicated
  "response" panel.
- Add prompt input to Web channel: add a chat-style input form, submit as
  S4 job, display LLM response in the UI.
- Wire the LLM response back through each channel's `send()` method as a
  rendered user-facing message (not just job metadata).
- Verify end-to-end flow: user prompt → channel → job → pipeline →
  real LLM call → response → channel → user sees answer.

Outcome:  
User can interact with VAI end-to-end via CLI, TUI, or Web channels.

---

## PHASE 4.8 — Observability & Telemetry
Goal: Add visibility into S4 behaviour.

✅ 4.8.1 — Metrics
- Job counts  
- Worker health  
- Queue depth  
- Execution time  
- Drift/repair frequency

✅ 4.8.2 — Logging
- Structured logs  
- Correlation IDs  
- Trace IDs

✅ 4.8.3 — Tracing
- Per‑job trace  
- Per‑cycle trace  
- Per‑segment trace

✅ 4.8.4 — Health Checks
- Liveness  
- Readiness  
- Worker pool health

✅ 4.8.5 — Observability Dashboard
- Web UI (SSE-streamed, single-page HTML/JS at http://localhost:8765)  
- Job list, worker list, trace viewer (hierarchical), metrics (histograms, drift), health
- Consumes S4 observability events via stdin/file pipe, never modifies state  
- `python -m src.platform.observability.dashboard` (stdin) or `--from-file events.jsonl`  

Outcome:  
S4 becomes inspectable, debuggable, and diagnosable.

---

## PHASE 4.9 — Deployment, Packaging, and Hardening
Goal: Make S4 shippable and maintainable.

✅ 4.9.1 — Configuration System
- env vars  
- config files  
- runtime overrides

✅ 4.9.2 — Deployment Targets
- local  
- container  
  - ℹ️ cloud was intentionally deferred

✅ 4.9.3 — Security Hardening
- auth  
- rate limiting  
- input validation  
- sandboxing

✅ 4.9.4 — Release Checklist
- invariants  
- determinism  
- safety  
- performance  
- concurrency  
- channels  
- observability  

✅ 4.9.5 — Documentation
- architecture  
- API  
- channels  
- lifecycle  
- control plane  
- worker pool  

Outcome:  
S4 is production‑ready.

---
🚀 Release 6 — "Multi-Agent System"
---

## Stratum architecture (revised)

```
External world
    │
    ▼
Gateway (CLI, HTTP, Slack, Cron, …)
    │   Ingress/egress, protocol normalization, external API surface
    ▼
S5: Agent + Workflow Layer
  ├── Agent definitions (YAML) — "I handle these workflow types"
  ├── Router — inspect input → pick agent → pick destination
  ├── State / History — conversation state, persona continuity
  ├── Workflow engine — orchestration, state machines, step execution
  │
  └──► Runtime — cross-cutting LLM service (used by S5, S2)
                │
                ▼
          S4b: Platform (queues, workers, supervision, durability)
                │
                ▼
          S2: Planner — multi-step plans, drift detection, error recovery
                │
                ▼
          S3: Capabilities — skills and primitives (file.read, web.search, …)
```

| Layer | Responsibility | Key invariant |
|---|---|---|
| **Gateway** | Ingress/egress, protocol normalization, external API | Never interprets content |
| **S5** | Agent definitions, routing, state, workflow orchestration | Never calls LLM directly, never owns transport |
| **S4b** | Queues, workers, supervision, durability | Never knows about agents |
| **S2** | Planning, drift detection, tool orchestration | Never knows about workflows |
| **S3** | Skills and primitives | Never initiates work |
| **Runtime** | Cross-cutting LLM service | Every layer above S4b calls it |

## STRATUM 5 — Agent Layer (Routing + Persona + Dispatch + Workflow)
S5 owns agent definitions, routing logic, conversation state, and workflow orchestration
(multi-step processes). Every LLM call is delegated to Runtime. Every tool call is delegated to Platform.
Every event is received from S4's event substrate. The workflow layer (phases 5.5+) handles
trigger routing, state machine execution, agent selection, and human-in-the-loop.

### PHASE 5.0 — Agent Definition Model + YAML Manifest (✅ Done)
**Implemented in**: `src/agent/registry.py`, `src/agent/loaders/yaml_loader.py`, `config/agents.yaml`
**Files created**: `src/agent/contracts.py` (AgentIdentity, AgentConstraints, AgentMetadata frozen dataclasses), `src/agent/loaders/yaml_loader.py` (YAML parser/validator), `config/agents.yaml` (declarative agent definitions)
**Status**: ✅ Complete

Outcome: Agents are declarative — create by editing a YAML file, no code changes.

### PHASE 5.1 — Agent State + History
**Implemented in**: `src/agent/supervisor.py`, `src/agent/interfaces/agent_state.py`, `src/agent/interfaces/agent_state_store.py`, `src/agent/adapters/memory_agent_state_store.py`, `src/agent/adapters/file_agent_state_store.py`, `src/agent/adapters/sqlite_agent_state_store.py`
**Files created**: LifecycleState enum, LifecycleEvent, AgentState frozen dataclass, AgentStateStore ABC, three backend adapters (in-memory, file, SQLite)
**Status**: ✅ Complete

Outcome: Agents have durable, resumable state with three storage backends.

### PHASE 5.2 — Agent Router (Replace Cognitive Loop) (✅ Done)
**Implemented in**: `src/agent/router.py`, `src/agent/supervisor.py`, `src/agent/job_interface.py`, `src/agent/contracts.py`

**Files changed**:
- `src/agent/router.py` — CREATED (Route dataclass, route_message() with deterministic keyword matching, 3 destinations)
- `src/agent/supervisor.py` — MODIFIED (simplified: removed cognitive loop, added route_and_dispatch())
- `src/agent/cognitive_loop.py` — DELETED
- `src/agent/contracts.py` — MODIFIED (removed ActionIntent, ACTION_CALL_TOOL_INTENT, ACTION_AGENT_STEP_INTENT, ACTION_REQUEST_S4_JOB_INTENT, VALID_ACTION_INTENT_TYPES)
- `src/agent/job_interface.py` — MODIFIED (dispatch_route() replaces dispatch_action_intents(); submit_job_callable pattern retained)
- `src/agent/__init__.py` — MODIFIED (updated exports)
- `tests/unit/agent/test_router.py` — CREATED (38 tests)
- `tests/unit/agent/test_supervisor.py` — MODIFIED (6 fixes: removed actions=[] params, cognitive_result→route_result)
- `tests/unit/agent/test_job_interface.py` — MODIFIED (rewritten for dispatch_route() API)
- `tests/unit/agent/test_cognitive_loop.py` — DELETED
- `tests/unit/agent/test_contracts.py` — MODIFIED (removed ActionIntent class tests)
- `tests/unit/agent/test_activation.py` — MODIFIED (removed stale ACTION_REQUEST_S4_JOB_INTENT import)
- `tests/unit/agent/test_agent_state_store.py` — MODIFIED (removed ActionIntent/Action types)

**Status**: ✅ Complete

Outcome: Agent is a thin router — inspect, match, dispatch. No cognitive loop, no intent types, no LLM calls in agent code. All 206 agent tests pass.

### PHASE 5.3 — CLI Channel Integration (✅ Done)
**Implemented in**: `tools/agent/cli_app.py`

**Files changed**:
- `tools/agent/cli_app.py` — MODIFIED (rewired from cognitive loop to `supervisor.run_agent_step()`; uses `call_s1_backend(backend="conversational")` as Runtime stand-in; interactive REPL, pipe mode, and agent selection retained)

**Status**: ✅ Complete

Outcome: CLI works end-to-end through the new router — user message → route → dispatch → response. No cognitive loop dependency. `vai> ` interactive mode and `echo "hello" | python -m tools.agent.cli_app` pipe mode both function.

### PHASE 5.4 — Integration Tests (✅ Done)
**Implemented in**: `tests/unit/agent/`

**Files changed**:
- `tests/unit/agent/test_router.py` — CREATED (38 tests covering Route dataclass validation, routing decisions, keyword matching, capability gating)
- `tests/unit/agent/test_supervisor.py` — MODIFIED (6 fixes: removed cognitive loop references, cognitive_result→route_result)
- `tests/unit/agent/test_job_interface.py` — MODIFIED (rewritten for dispatch_route() API, 8 tests)
- `tests/unit/agent/test_cognitive_loop.py` — DELETED
- `tests/unit/agent/test_contracts.py` — MODIFIED (removed ActionIntent class tests)
- `tests/unit/agent/test_activation.py` — MODIFIED (removed stale ACTION_REQUEST_S4_JOB_INTENT import)
- `tests/unit/agent/test_agent_state_store.py` — MODIFIED (removed ActionIntent/Action types)

**Status**: ✅ Complete — all 206 agent tests pass.

Outcome: S5 is tested and stable with the new router architecture.

## PHASE 5.5 — Workflow Definition Model
The workflow layer sits inside S5 (phases 5.5—5.11). It owns workflow definitions,
state machine execution, and orchestration of multi-step processes. Workflow receives
triggers via S4's event substrate, delegates LLM work to Runtime, and delegates tool
execution to Platform.

Design the workflow schema. A workflow is a directed graph of steps that share context.
This phase produces the data model and YAML loader — no execution yet.

**Files to create:**
- `src/agent/workflow/workflow_definition.py` — pydantic models
- `src/agent/workflow/loaders/yaml_loader.py` — YAML parser with validation
- `src/agent/workflow/registry.py` — WorkflowRegistry (in-memory)
- `config/workflows/demo_chat.yaml` — sample workflow
- `tests/unit/agent/workflow/test_workflow_definition.py` — tests

**Step types:**
| Step Type | Purpose | Config Fields |
|-----------|---------|---------------|
| `llm_call` | Call Runtime with a prompt | `system_prompt`, `model` |
| `tool_execute` | Submit job to S4b Platform | `tool_name`, `params` |
| `sub_workflow` | Invoke another workflow | `workflow_id`, `input_map` |
| `user_input` | Await human input | `prompt`, `input_schema` |
| `condition` | Branch logic | `expression` (context path) |

**Validation rules (all raise ValidationError):**
- No orphan steps (all transition targets reference valid step_ids)
- `start_step` exists in the steps dict
- Graph is acyclic (use topological sort to detect cycles)
- Each step's `transitions` dict must contain at least one of `on_success`, `on_failure`, `on_timeout`, `on_cancel`
- No duplicate `step_id` values
- `__end__` is a reserved transition target (means "workflow complete")

**Implement `WorkflowDefinition` model:**
```python
class WorkflowStep(BaseModel):
    step_id: str
    step_type: Literal["llm_call", "tool_execute", "sub_workflow", "user_input", "condition"]
    label: str
    description: str | None = None
    config: dict[str, Any] = {}
    transitions: dict[str, str] = {}  # {"on_success": "next_step_id", "on_failure": "__end__"}
    timeout_seconds: float | None = None
    retry_policy: dict | None = None  # {"max_retries": 3, "backoff_factor": 2.0}

class WorkflowDefinition(BaseModel):
    workflow_id: str
    name: str
    description: str
    version: str = "1.0.0"
    trigger_on: list[str] = []        # S4 event types that start this workflow
    input_schema: dict | None = None   # expected input shape
    steps: dict[str, WorkflowStep]    # step_id → step
    start_step: str
    shared_context_schema: dict | None = None
    timeout: float | None = None      # total workflow timeout
    required_agent_tags: list[str] = []  # for agent selection (Phase 6.3)
```

**Implement YAML loader** in `src/agent/workflow/loaders/yaml_loader.py`:
```python
def load_workflow(path: str) -> WorkflowDefinition:
    # 1. Read YAML file
    # 2. Parse into WorkflowDefinition via pydantic (validates types)
    # 3. Run additional graph validation (acyclic, transitions exist)
    # 4. Return validated definition or raise ValidationError
```

**Implement `WorkflowRegistry`** in `src/agent/workflow/registry.py`:
```python
class WorkflowRegistry:
    def register(self, defn: WorkflowDefinition) -> None: ...
    def get(self, workflow_id: str) -> WorkflowDefinition | None: ...
    def list(self) -> list[WorkflowDefinition]: ...
    def find_by_trigger(self, event_type: str) -> list[WorkflowDefinition]: ...
```

**Write tests** (`tests/unit/agent/workflow/test_workflow_definition.py`):
1. Create valid workflow → all fields match input
2. Missing start_step → raises ValidationError
3. Transition to non-existent step → raises ValidationError
4. Cyclic graph (A→B→C→A) → raises ValidationError
5. No transitions dict → raises ValidationError
6. YAML round-trip: load YAML string → WorkflowDefinition → serialize to dict
7. Empty steps dict → raises ValidationError
8. Invalid step_type → raises ValidationError
9. Registry: register → get → returns same definition
10. Registry: find_by_trigger → returns only matching workflows

✅ Outcome: Workflows are declarative YAML files validated as acyclic directed graphs.

### PHASE 5.6 — Workflow Engine (State Machine)
The core execution engine. A state machine that runs workflow steps, manages shared context, handles transitions, and exposes a clean API. The engine NEVER calls LLMs or tools directly — it delegates through APIs.

**Critical architectural rule:** `llm_call` steps use a Runtime API function. `tool_execute` steps use a Platform API function. The engine receives these as callbacks — it does not import transport.py or skill_runner.py.

**Files to create:**
- `src/agent/workflow/engine.py` — WorkflowEngine, WorkflowInstance, StepResult
- `tests/unit/agent/workflow/test_engine.py` — comprehensive tests

**Implement `WorkflowInstance`:**
```python
@dataclass
class WorkflowInstance:
    instance_id: str
    workflow_id: str
    state: Literal["pending", "running", "paused", "succeeded", "failed", "cancelled", "timeout"]
    current_step_id: str | None
    shared_context: dict[str, Any]
    step_history: list[StepResult]
    created_at: float
    updated_at: float
    error: str | None = None
```

**Implement `WorkflowEngine`:**
```python
class WorkflowEngine:
    def __init__(self, runtime_api: Callable, platform_api: Callable):
        # runtime_api: call(agent_id, message, context) -> {"text": str, ...}
        # platform_api: submit_job(tool_name, params) -> {"result": ...}
        ...
    def start(self, defn: WorkflowDefinition, initial_input: dict) -> str:
        # Create instance, set state=running, call _execute_step, return instance_id
    def resume(self, instance_id: str, input: dict | None = None) -> None:
        # Resume a paused workflow (user provided input)
    def cancel(self, instance_id: str) -> None: ...
    def get_status(self, instance_id: str) -> WorkflowInstance | None: ...
```

**Implement `_execute_step()` logic:**
1. Load current step from definition
2. Build context from `shared_context` + step history
3. Based on `step_type`:
   - **`llm_call`**: Build system prompt from config (support `{context.key}` placeholders). Call `runtime_api(agent_id, message, system_prompt)`. Store result in `shared_context["last_output"]`.
   - **`tool_execute`**: Call `platform_api.submit_job(tool_name, params_with_substitutions)`. Store result in `shared_context["last_tool_result"]`.
   - **`user_input`**: Set state to `"paused"`. Store InteractionRequest. Return — execution resumes via `resume()` which calls `_execute_step()` again.
   - **`condition`**: Evaluate expression against context (simple dict path lookup: `context.x > 5` → check `context["x"] > 5`). Choose transition based on boolean.
   - **`sub_workflow`**: Recursively call `start(sub_defn, input)`. Wait for completion. Fold child's shared_context into parent's.
4. On success: follow `transitions["on_success"]`. If `"__end__"`, set state to `"succeeded"`.
5. On error: follow `transitions["on_failure"]` if defined, else set state to `"failed"`.
6. On timeout: follow `transitions["on_timeout"]` if defined, else set state to `"timeout"`.
7. Record `StepResult` in `instance.step_history` after each step.

**Write tests** (`tests/unit/agent/workflow/test_engine.py`):
1. Linear workflow (3 llm_call steps) → executes all in order → state="succeeded"
2. Workflow with condition step → follows correct path based on context value
3. Workflow with tool_execute → calls platform_api with correct params
4. Workflow with user_input → state="paused" → resume() → continues → state="succeeded"
5. Workflow where step fails with on_failure → follows fallback path → state="succeeded"
6. Workflow where step fails without on_failure → state="failed"
7. Cancel running workflow → state="cancelled"
8. Timeout (simulate slow step) → state="timeout"
9. Sub-workflow execution → parent waits → child completes → parent resumes → correct context merge
10. Shared context accumulates across steps (step 2 can read step 1's output)

✅ Outcome: Fully functional workflow state machine. Tested across all step types, transitions, and error paths.

### PHASE 5.7 — Workflow Trigger Router
The workflow layer receives signals from S4's event substrate. This phase builds the trigger router that subscribes, filters, and maps events to workflow instances.

**Files to create:**
- `src/agent/workflow/trigger_router.py` — TriggerRouter, WorkflowEvent
- `src/agent/workflow/event_bus.py` — lightweight in-process event bus (stand-in for S4b)
- `tests/unit/agent/workflow/test_trigger_router.py` — tests

**Implement `WorkflowEvent` and `TriggerRouter`:**
```python
@dataclass(frozen=True)
class WorkflowEvent:
    event_type: str       # "workflow.start" | "workflow.resume" | "workflow.timeout" | etc.
    payload: dict
    correlation_id: str
    timestamp: float

class TriggerRouter:
    def __init__(self, registry: WorkflowRegistry, engine: WorkflowEngine):
        self._registry = registry
        self._engine = engine

    async def handle_event(self, event: WorkflowEvent) -> str | None:
        # 1. Find workflows where trigger_on matches event.event_type
        # 2. For each match: call engine.start(defn, event.payload)
        # 3. Return last instance_id or None if no match

    def subscribe_to(self, event_types: list[str], event_bus) -> None:
        # Register interest in specific event types
```

**Implement lightweight event bus** (stand-in until S4b provides this):
```python
class EventBus:
    def __init__(self): ...
    def subscribe(self, event_type: str, handler: Callable) -> None: ...
    def publish(self, event: WorkflowEvent) -> None: ...
    # Contract mirrors what S4b's event substrate will eventually provide
```

**Wire trigger router to event bus:**
- On init: scan registry for all trigger_on values, subscribe to each
- On event publish: route through TriggerRouter.handle_event()
- Log all routing decisions

**Write tests** (`tests/unit/agent/workflow/test_trigger_router.py`):
1. Publish matching event → workflow instance created → instance_id returned
2. Publish non-matching event → no workflow instance → returns None
3. Multiple workflows match same event type → all start → list of instance_ids
4. Event with no subscriber → logged, no error, returns None
5. Event with matching correlation_id → instance has correlation_id in context
6. Resume event for paused workflow → engine.resume() called instead of engine.start()

✅ Outcome: The workflow layer has a clean ingress for events without owning transport. Stand-in event bus enables independent development.

### PHASE 5.8 — Agent Selection Layer
Given a workflow, select the correct agent from S5's registry. This is the glue between the workflow layer (what to do) and the agent layer (who does it).

**File to create:** `src/agent/workflow/agent_selector.py`
**Test file:** `tests/unit/agent/workflow/test_agent_selector.py`

**Implement `AgentSelector`:**
```python
class AgentSelector:
    def __init__(self, agent_registry):
        # agent_registry from src/agent/registry.py

    def select_for_workflow(self, defn: WorkflowDefinition) -> AgentHandle | None:
        # 1. Get all agents from registry
        # 2. Filter by: defn.workflow_id in agent.constraints.allowed_workflows
        # 3. Score by tag overlap (len(agent.tags ∩ defn.required_agent_tags))
        # 4. Return highest-scoring agent, or None if empty

    def select_for_step(self, defn: WorkflowDefinition, step: WorkflowStep) -> AgentHandle | None:
        # Step-level override (step.config may specify "agent_id" or "agent_tags")
        # Falls back to select_for_workflow if step has no override
```

**Integrate with engine:**
- When engine starts a workflow, call `agent_selector.select_for_workflow()`, store agent_handle on WorkflowInstance
- On `llm_call` steps: inject the selected agent's persona/system prompt into the call
- On `tool_execute` steps: tag the job with agent_id for tracing
- If no agent matches: raise `NoSuitableAgentError`, set state to `"failed"`, record error

**Write tests:**
1. Workflow with matching agent → returns correct AgentHandle
2. Workflow with no matching agent → returns None → engine raises error
3. Workflow with multiple matching agents → returns best match (highest tag overlap)
4. Step-level override → returns step-specific agent (different from workflow-level)
5. Step with no override → falls back to workflow-level agent
6. Agent tags match exactly → highest score
7. Agent tags partial match → lower score but still returned

✅ Outcome: Workflow engine auto-selects the right S5 agent for each workflow.

### PHASE 5.9 — Human-in-the-Loop
Workflows need to pause for human input. This phase builds the interaction manager that handles the pause → present → validate → resume cycle.

**File to create:** `src/agent/workflow/user_interaction.py`
**Test file:** `tests/unit/agent/workflow/test_user_interaction.py`

**Implement `UserInteractionManager`:**
```python
@dataclass
class InteractionRequest:
    request_id: str
    instance_id: str
    step_id: str
    prompt: str
    input_schema: dict[str, Any]
    timeout_seconds: float | None
    created_at: float

@dataclass
class InteractionResponse:
    request_id: str
    data: dict[str, Any]
    received_at: float

class UserInteractionManager:
    def __init__(self, engine: WorkflowEngine): ...

    def request_input(self, instance_id: str, step_id: str,
                      prompt: str, schema: dict) -> InteractionRequest:
        # 1. Create InteractionRequest
        # 2. Register with engine (pauses workflow)
        # 3. Return request for outer layer to display

    def submit_response(self, request_id: str, data: dict) -> bool:
        # 1. Validate data against input_schema (basic type checks)
        # 2. If valid: call engine.resume(request_id, data), return True
        # 3. If invalid: return False, error detail in log
```

**Integrate with engine:**
- In `_execute_step()`, when step_type is `user_input`:
  1. Call `interaction_manager.request_input(instance_id, step_id, prompt, schema)`
  2. Set state to `"paused"`, store the InteractionRequest
  3. Return — execution stops. CLI/API receives the InteractionRequest
- When user responds, CLI calls `interaction_manager.submit_response(request_id, data)`
- InteractionManager calls `engine.resume(instance_id, data)`
- Engine stores data in shared_context and continues execution

**Write tests:**
1. Request input → InteractionRequest created with correct fields (prompt, schema, step_id)
2. Submit valid → validates → calls engine.resume() → returns True
3. Submit invalid (wrong type) → returns False, engine not called
4. Submit invalid (missing field) → returns False, engine not called
5. Timeout (simulate) → engine transitions to timeout state
6. Multiple concurrent workflows with pending input → each tracked independently
7. Same workflow, two user_input steps in sequence → first completes, second starts after resume

✅ Outcome: Workflows can pause for human input with validation. CLI can display prompts and collect responses.

### PHASE 5.10 — Platform Integration
The workflow engine must route all external calls through Platform (S4b). Currently the engine may call Runtime directly — this phase routes everything through Platform's API.

**File to create:** `src/agent/workflow/platform_adapter.py`
**Test file:** `tests/unit/agent/workflow/test_platform_adapter.py`

**Implement `PlatformAdapter`:**
```python
class PlatformAdapter:
    def __init__(self, submit_job_fn):  # S4b's job submission function
        self._submit_job = submit_job_fn

    def call_runtime(self, agent_id: str, message: str, context: dict) -> dict:
        # Wraps LLM call as Platform job: submit → wait → return result
        # Future: Platform handles retries, queuing, supervision
        # For now: direct call to Runtime, wrapped in Platform job envelope

    def execute_tool(self, tool_name: str, params: dict) -> dict:
        # Submits tool execution job via Platform
        # Platform → S2 → S3 execution chain

    def send_output(self, user_id: str, message: str) -> None:
        # Sends output through Platform egress
```

**Replace direct calls in `WorkflowEngine`:**
- `engine._runtime_api` → `platform_adapter.call_runtime()`
- `engine._platform_api.execute_tool()` → `platform_adapter.execute_tool()`
- No code in the workflow layer imports `transport.py`, `s1_client.py`, or `skill_runner.py`

**Update engine constructor:**
```python
class WorkflowEngine:
    def __init__(self, platform_adapter: PlatformAdapter):
        # PlatformAdapter wraps Runtime and Platform APIs
        ...
```

**Write tests:**
1. `call_runtime()` → submits job → returns result dict
2. `execute_tool()` → submits job → returns result dict
3. `send_output()` → submits job → no error
4. Adapter passes correct parameters to underlying submit_job_fn
5. Engine tests still pass after swap (update engine test fixtures to use PlatformAdapter)
6. Verify no direct imports of transport/skill_runner in any src/agent/workflow/ file

✅ Outcome: Platform is the only execution conduit for the workflow layer.

### PHASE 5.11 — Workflow Supervisor
Operational layer for observing and managing all running workflow instances.

**File to create:** `src/agent/workflow/supervisor.py`
**Test file:** `tests/unit/agent/workflow/test_supervisor.py`

**Implement `WorkflowSupervisor`:**
```python
class WorkflowSupervisor:
    def __init__(self, engine: WorkflowEngine): ...

    def list_instances(self, state: str | None = None) -> list[WorkflowInstance]:
        # Filter by optional state; sorted by created_at desc

    def get_instance(self, instance_id: str) -> WorkflowInstance | None:
        # Full detail: step_history, shared_context, error

    def cancel_instance(self, instance_id: str) -> bool:
        # Cancel a running/paused workflow

    def retry_instance(self, instance_id: str) -> bool:
        # Reset a failed workflow to re-run from last failed step
        # (Resets state to "running", clears error, preserves context)

    def dead_letter_queue(self) -> list[WorkflowInstance]:
        # Instances that have exceeded retry limits or have unrecoverable errors

    def metrics(self) -> dict:
        # Counts by state, avg duration, failure rate
        # Return: {"active": 5, "completed": 100, "failed": 3, "avg_duration_ms": 450}
```

**Add observability:**
- Structured logs at each state transition (same format as S4's control_plane traces)
- Metrics: `workflow.active.count`, `workflow.duration_ms`, `workflow.failure.rate`
- Integration point for S2 drift-detection (future)

**Write tests:**
1. List all instances → returns correct count and items
2. Filter by state="running" → only running instances
3. Get specific instance → returns full detail including step_history
4. Cancel running instance → state changes to "cancelled"
5. Cancel already-cancelled instance → returns False (no-op)
6. Retry failed instance → state = "running", error cleared, step_history preserved
7. Retry succeeded instance → returns False (no-op)
8. Dead letter tracking → instances past retry limit appear in DLQ
9. Metrics → correct counts for mixed-state instances
10. Concurrent instances from different workflows → all tracked separately

✅ Outcome: Operations team can observe, manage, and debug running workflows.

## Runtime — Cross-Cutting LLM Service

Runtime is not a stratum — it is a service used by S5 and S2.
Every layer above S4b calls Runtime when it needs LLM cognition.

**Note on naming:** The existing `src/strategy/planning/s1_contract/` directory and `s1_real_client.py` are legacy names from when Runtime was "Strategy 1". They need to be renamed (but rename is done in Phase R.2 — keep functional changes separate from renames).

### PHASE R.1 — Runtime Contract
Define the Runtime API that all calling layers (S5, S2) will use. This is a contract-first phase — no implementation changes yet.

**File to create:** `src/runtime/contract.py`

**Contract:**
```python
@dataclass(frozen=True)
class RuntimeResponse:
    text: str
    tool_calls: list[dict] | None = None  # [{name: str, arguments: dict}]
    confidence: float = 0.95
    usage: dict | None = None  # {"input_tokens": int, "output_tokens": int}

@dataclass(frozen=True)
class RuntimeConfig:
    provider: str              # "deepseek" | "openai" | "anthropic" | "simulation" | "mock"
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096

class Runtime:
    @staticmethod
    def complete(prompt: str, context: dict | None = None,
                 config: RuntimeConfig | None = None) -> RuntimeResponse:
        # Central LLM call — all layers use this
        ...
```

**Design rules:**
- Single `complete()` method for all LLM calls
- `context` carries system_prompt, chat history, tool definitions, persona
- `config` allows per-call model override (caller hints the model, Runtime resolves it)
- Return always includes `text` (the response); `tool_calls` is optional (for structured-mode calls)
- No layer-specific logic — Runtime does NOT know about workflows, agents, or plans

**Write contract tests** (`tests/unit/runtime/test_contract.py`):
1. RuntimeResponse can be created with just text
2. RuntimeResponse with all fields
3. RuntimeConfig defaults match expected values
4. RuntimeConfig accepts all valid provider values
5. Contract is frozen (immutable) — can't modify fields after creation

✅ Outcome: Clean, agreed Runtime API contract before implementation begins.

### PHASE R.2 — Runtime Implementation
Build the Runtime service over the existing LLM transport. This phase moves `call_s1_backend()` logic into Runtime and renames the legacy directories.

**Note on line counts:** `s1_client.py` is ~200 lines, `s1_real_client.py` is ~150 lines. The old files remain as wrappers until all callers are migrated in Phase R.3, then they're deleted.

**Step 1 — Create `src/runtime/` module:**

- Create `src/runtime/__init__.py` that exports the public API
- Create `src/runtime/implementations`
- Create `src/runtime/implementations/__init__.py`

**Step 2 — Create `src/runtime/implementations/transport_runtime.py`:**
```python
class TransportRuntime(Runtime):
    """Uses the existing LLM transport (from src/strategy/llm/transport.py)."""

    def complete(self, prompt: str, context: dict | None = None,
                 config: RuntimeConfig | None = None) -> RuntimeResponse:
        # 1. Load config.yaml for LLM settings
        # 2. Create LLMTransport with appropriate model/provider
        # 3. Call transport.complete() with prompt + context
        # 4. Return RuntimeResponse wrapping the raw text
```

This is essentially what `call_s1_backend(backend="conversational")` does, but in the proper Runtime module.

**Step 3 — Create supporting implementations:**
- `src/runtime/implementations/mock_runtime.py` — returns canned responses (for tests)
- `src/runtime/implementations/simulation_runtime.py` — returns realistic but fake responses (for demos)

**Step 4 — Rename legacy directories (purely a rename, no logic changes):**
- `src/strategy/planning/s1_contract/` → `src/runtime/contract/` (only if s1_contract.py is the old contract)
  - **Wait:** Check what's actually in `s1_contract/` first — it may contain more than just contract code
  - If it's just the contract → move to `src/runtime/contract.py`
  - If it has implementations too → split: contract to `src/runtime/contract.py`, implementations stay until migrated
- `src/strategy/planning/s1_real_client.py` → `src/runtime/implementations/real_llm_client.py`
  - Create a thin wrapper that the old import path (`s1_real_client.py`) re-exports for backward compat

**Step 5 — Update `config/config.yaml`:** Add `runtime` section alongside existing LLM config:
```yaml
runtime:
  default_provider: deepseek
  default_model: deepseek-chat
  providers:
    deepseek:
      api_key_env: DEEPSEEK_API_KEY
      base_url: https://api.deepseek.com
    simulation:
      response_delay_ms: 100
```

**Write implementation tests** (`tests/unit/runtime/test_transport_runtime.py`):
1. TransportRuntime.complete() returns RuntimeResponse with text
2. Empty prompt returns empty text (no crash)
3. Config overrides provider correctly
4. Context with system_prompt is included in the call
5. Error from transport layer is wrapped (not propagated raw)

✅ Outcome: Runtime exists as a proper module. Legacy files renamed. The `call_s1_backend()` pattern is deprecated (not removed yet — callers migrate in R.3).

### PHASE R.3 — Runtime Integration
Migrate all callers from the old `s1_client.py` / `s1_real_client.py` pattern to the new Runtime API.

**Files to modify:**
- `src/agent/supervisor.py` — old code probably imports `call_s1_backend` or `s1_real_client`
- `tools/agent/cli_app.py` — may import s1_client directly
- Any test fixtures or mocks that reference old s1_* names

**Step 1 — Audit all imports:**
```bash
grep -r "s1_client\|s1_real_client\|s1_contract\|call_s1_backend" src/ tools/ tests/
```
Every hit is a caller that needs to be migrated.

**Step 2 — Migrate each caller:**
- Replace `from src.strategy.planning.s1_contract.s1_client import call_s1_backend` with `from src.runtime.implementations.transport_runtime import TransportRuntime; runtime = TransportRuntime(); runtime.complete(...)`
- Update call sites: old pattern passes `request.prompt["message"]` → new pattern passes `prompt=str, context={"system_prompt": ..., "history": ...}`
- Update tests to use `MockRuntime` instead of mocking `call_s1_backend`

**Step 3 — Verify no old imports remain:**
```bash
grep -r "s1_client\|s1_real_client\|s1_contract\|call_s1_backend" src/ tools/ tests/
```
Should return zero matches (if not, migrate remaining).

**Step 4 — Remove legacy files:**
- Delete `src/strategy/planning/s1_contract/s1_client.py` (or the whole s1_contract dir if empty)
- Delete `src/strategy/planning/s1_real_client.py` (after removing backward-compat wrapper)
- Update `src/strategy/planning/__init__.py` to remove old exports

**Step 5 — Integration test:**
```bash
python -m tools.agent.cli_app
# Type a message → Runtime handles the LLM call → response displays
```
End-to-end: CLI → S5 router → Runtime.complete() → DeepSeek → response.

**Write migration tests** (`tests/integration/runtime/test_runtime_integration.py`):
1. Runtime called from S5 context → completes successfully
2. Runtime called with empty context → still completes
3. MockRuntime returns expected canned response
4. Migration didn't break any existing agent/supervisor tests

✅ Outcome: All callers use the new Runtime API. Legacy s1_* files are deleted. End-to-end test confirms the path works.

## X Hardening, Resilience ---

### PHASE X.1 — Resilience, Self‑Healing, Health

X.1.1. Classify loop health — healthy, stalled, poisoned.  
X.1.2. Detect stalled loops  
X.1.3. Auto‑abort stalled loops  
X.1.4. Auto‑downgrade behaviour  
X.1.5. Add global watchdog  
X.1.6. Add auto‑scaling hooks  
X.1.7. Add panic reporting  
X.1.8. Add resilience tests  
X.1.9. Add recovery drills  
X.1.10. Document failure modes

---
🚀 Release 7 — "Production-Ready Runtime"
---

### PHASE X.2 — Observability & Developer Experience

X.2.1. Add structured logging  
X.2.2. Add metrics exporter  
X.2.3. Add tracing spans  
X.2.4. Add flamegraph timings  
X.2.5. Add local dev CLI  
X.2.6. Add replay tooling  
X.2.7. Add config inspector  
X.2.8. Add skill inspector  
X.2.9. Add agent inspector  
X.2.10. Add end‑to‑end smoke tests

---
🚀 Release 8 — "Observable and Developer-Friendly Runtime"
---

### PHASE X.3 — Hardening & Polish

X.3.1. Security review of skills  
X.3.2. Security review of fetch stack  
X.3.3. LLM prompt hardening  
X.3.4. Config profiles — dev, prod, paranoid.  
X.3.5. Backwards‑compatible APIs  
X.3.6. Performance tuning  
X.3.7. Load testing  
X.3.8. Graceful degradation strategy  
X.3.9. Disaster recovery story  
X.3.10. Write architecture doc — for future contributors.

---
🚀 Release 9 — "Hardened Runtime"
---

## Y - Cognitive Systems and Meta-Agents
*Note*: Future considerations of what is possible, rather than on the roadmap

### PHASE Y.1 - Meta-Planning and Self-Reflection

### PHASE Y.2 - Long-Term Memory and Knowledge Graphs

### PHASE Y.3 - Multi-Agent Societies

### PHASE Y.4 - Tool Learning and Skill Synthesis

### PHASE Y.5 - Autonomy and Governance

---
