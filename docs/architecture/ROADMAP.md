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

✅ 2.13.4 — Release 1 Validation
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

---

🚀 Release 1 — "Hierarchical Reasoner"
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

3.10.1 — FetchError taxonomy
- Dataclasses: `TimeoutError`, `HTTPError` (status_code, body), `ParseError`, `ConnectionError`

3.10.2 — `stdlib.http.fetch` primitive
- httpx GET with configurable timeout, headers, status-code handling
- Returns: `status_code`, `body` (str), `headers` (dict), `elapsed` (ms)

3.10.3 — `fetch_url` skill
- Wires to `http.fetch` primitive; returns status + body + headers
- Accepts `url` and optional `timeout`, `headers` args

3.10.4 — Tests
- Successful fetch, timeout, 4xx response, 5xx response, connection refused, invalid URL

---

### PHASE 3.11 — Fetch Orchestrator: Hardened Modes
*Depends On*: PHASE 3.10

3.11.1 — Hardened HTTP fetch mode
- Anti-bot headers (rotating User-Agent, Accept-Language), retry with exponential backoff, cookie jar

3.11.2 — Playwright headless fetch mode
- JS rendering via Playwright; handles SPA and JS-dependent content

3.11.3 — Playwright stealth fetch mode
- Stealth plugin, human-like timing, rate limiting, fingerprint masking

3.11.4 — Tests
- Each mode exercised against a known endpoint; mode-selection by flag; fallback on mode failure

---

### PHASE 3.12 — Fetch Orchestrator: Escalation & Domain Policy
*Depends On*: PHASE 3.11

3.12.1 — Fetch heuristics
- Select initial mode based on URL pattern, content-type hints, prior success/failure history

3.12.2 — Fallback chain
- `simple → hardened → browser → stealth → search`; each step triggered by `FetchError` type
- Mode-specific timeouts: simple (10s), hardened (15s), browser (30s), stealth (45s)

3.12.3 — Per-domain policy
- Allowlists, deny lists, rate limits, mode preferences per domain
- Configurable via `domain_policy.json` or equivalent

3.12.4 — Single LLM-facing interface
- Expose only `fetch_url` skill; internal strategies (modes, escalation, policy) hidden behind it
- LLM sees `fetch_url(url)` — nothing else

3.12.5 — Tests
- Escalation triggers correctly per error type; fallback transitions observed; policy enforces allow/deny; rate limiting honoured

---

### PHASE 3.13 — Search Provider
*Depends On*: PHASE 3.12

Depends on fetch infrastructure (simple HTTP) to retrieve search results.

3.13.1 — Search primitive
- Query → list of URLs with titles and snippets; uses fetch_url internally

3.13.2 — `search_urls` skill
- Wraps search primitive; normalises results; returns structured list

3.13.3 — Wire into fetch fallback
- When all fetch modes fail, search for alternative sources as last-resort fallback

3.13.4 — `GetPageFromUrl` taxonomy
- Define content type taxonomy (article, documentation, blog, unknown) for multimodal retrieval

3.13.5 — Tests
- Search returns results; fetch fallback triggers search; search results are usable by downstream fetch

---

### PHASE 3.14 — Plugin System
*Depends On*: PHASE 3.7

Users can drop in new primitives and skills with no code changes. Hot-loadable.

3.14.1 — Plugin manifest format
- `plugin.yml`: name, version, primitives (list), skills (list), dependencies

3.14.2 — Plugin loader
- Scans plugin directories, loads manifests, registers primitives + skills into registries

3.14.3 — Hot-reload
- Detect new/removed/modified plugins on file system changes; reload without restart

3.14.4 — Plugin authoring guide
- Document plugin structure, manifest schema, and examples in `docs/`

3.14.5 — Tests
- Load plugin, execute plugin skill, unload/reload cycle, invalid manifest rejection, version conflict handling

---

### PHASE 3.15 — Deterministic Plugin Hot-Reload
*Depends On*: PHASE 3.14

Versioned, stable registries ensure hot-reloading plugins does not violate S2's determinism invariants.

3.15.1 — Stable registry ordering
- Sort by skill name → version → plugin name
- Guarantees deterministic iteration order across reloads

3.15.2 — Stable embedding IDs
- Hash of skill name + version + manifest hash
- Embedding IDs remain stable across reloads

3.15.3 — Registry snapshots
- On plugin change: compute new snapshot, freeze it, expose snapshot ID to S2
- S2 uses snapshot ID for deterministic planning

3.15.4 — Hot-reload flow
- Load plugin → rebuild registry → compute snapshot → freeze → notify S2
- S2 can continue with old snapshot or switch at a safe boundary

3.15.5 — Tests
- Same plugin set produces identical snapshot IDs
- Snapshot stability across registry rebuilds
- S2 snapshot selection and boundary switching

---

### PHASE 3.16 — Agent-Authored Skills (Future)
*Depends On*: PHASE 3.9

The agent can author new `.skill.md` files, propose new primitives, and extend its own capability layer.

3.16.1 — Skill authoring pipeline
- LLM writes `.skill.md` content; submitted to registry via validation gate

3.16.2 — Safety checks
- Validate all referenced primitives exist; input schemas are safe; no privilege escalation patterns
- Reject skills that reference disallowed primitives or attempt to override system skills

3.16.3 — Validation + embedding update
- Validated skills are registered and embedded; immediately discoverable by future S2 planning

3.16.4 — Tests
- Agent authors a valid skill, exercises it; validation rejects dangerous skills; authored skill appears in discovery results

---

### PHASE 3.17 — Agent-Authored Skill Safety Layer
*Depends On*: PHASE 3.16

Layered safety gates for agent-authored skills: structural, semantic, behavioural, and governance.

3.17.1 — Structural safety
- Validates: no recursive skill references, no unbounded loops, no dynamic primitive selection
- Extends existing primitive-existence, schema, and privilege-escalation checks

3.17.2 — Semantic safety
- Validator checks: skill description matches behaviour, no domain-policy bypass
- Also checks: no chaining of high-risk primitives, no embedded user code

3.17.3 — Behavioural safety
- Run authored skill in sandbox with mock primitives and side-effect tracking
- Reject on unexpected side-effects

3.17.4 — Governance
- Skill provenance (author, timestamp), versioning, optional signing
- Quarantine until validated; approval workflow

3.17.5 — Tests
- Validator rejects recursive references, policy bypass, high-risk primitive chains
- Sandbox captures unexpected side-effects
- Quarantine/approval workflow exercised

---

### PHASE 3.18 — Standard Library v2 (Full stdlib)
*Depends On*: PHASE 3.7

Expands the MVP stdlib to a comprehensive, well-organised standard library across ten capability families.

3.18.1 — Ultra-Low-Level File Primitives
- `file.read`, `file.readhead`, `file.readtail`, `file.readrange`
- `file.exists`, `file.list`, `file.search`, `file.glob`, `file.stat`
- `file.write`, `file.append`, `file.delete`

3.18.2 — Structured Data Primitives
- `json.parse`, `json.get`, `json.set`
- `yaml.parse`, `toml.parse`
- `markdown.parse`, `html.parse`, `html.select`, `pdf.extracttext`
- `csv.read`, `csv.write`

3.18.3 — Database Primitives (Safe CRUD)
- `db.connect`, `db.query`, `db.insert`, `db.update`, `db.delete`
- `db.listtables`, `db.describetable`

3.18.4 — Network Primitives
- `net.httpget`, `net.httppost`, `net.dnslookup`, `net.ping`, `net.tcpcheck`

3.18.5 — Web Interaction Primitives
- `fetch.simple`, `fetch.hardened`, `fetch.browser`, `fetch.stealth`
- `search.web`

3.18.6 — Text & Document Processing
- `text.split`, `text.join`, `text.replace`, `text.extract`, `text.normalize`
- `doc.detecttype`, `doc.extractmetadata`

3.18.7 — System & Environment Primitives
- `sys.envget`, `sys.envlist`, `sys.timenow`, `sys.uuid`, `sys.tempfile`

3.18.8 — Process & Execution Primitives
- `proc.exec`, `proc.execsafe`, `proc.kill`, `proc.ps`
- (Optional; many runtimes omit for safety.)

3.18.9 — Compression & Encoding
- `zip.extract`, `zip.create`, `gzip.compress`, `gzip.decompress`
- `base64.encode`, `base64.decode`

3.18.10 — Tests
- Each primitive exercised end-to-end via SkillExecutor
- Category-level conformance suites (file, data, network, web, text, db, sys, proc, compression)

---

🚀 Release 3 — "Extensible Agent"
---

## STRATUM 4 - Distributed Runtime and System Infrastructure
*Invariant*: Provides distributed execution, workers, queues, channels  

### PHASE 4.1 — Queue & Job Model
*Depends On*: PHASE 3.3

4.1.1. Choose queue backend — Redis/SQLite.  
4.1.2. Define Job envelope — id, payload, metadata.  
4.1.3. Define JobResult envelope — status, result, error.  
4.1.4. Implement enqueue API  
4.1.5. Implement dequeue API  
4.1.6. Implement result store  
4.1.7. Add dead‑letter queue  
4.1.8. Add queue metrics  
4.1.9. Add priority queues  
4.1.10. Add backpressure handling

---
🚀 Release 4 — "Distributed Agent Runtime"
---

### PHASE 4.2 — Worker Pool & Supervision
*Depends On*: PHASE 4.1

4.2.1. Implement worker entrypoint — dequeue → CoreStep → store result.  
4.2.2. Add worker config — concurrency, queues, limits.  
4.2.3. Add worker telemetry  
4.2.4. Add worker heartbeat  
4.2.5. Implement worker supervisor — restart on crash.  
4.2.6. Add graceful shutdown  
4.2.7. Add worker circuit breaker  
4.2.8. Add job cancellation  
4.2.9. Add job timeouts  
4.2.10. Add heavy‑skill worker pool — browser/stealth.

---
🚀 Release 5 — "API-Driven Agent Platform"
---

### PHASE 4.3 — FastAPI & WebSocket Layer
*Depends On*: PHASE 4.2  
*Note*: This is currently opinionated around what human interaction should look like (rather than decisions made in the previous version of this project). When this gets a bit closer, it needs a strategy around channels, abstractions, etc.  

4.3.1. Define Channel interface — receive → runtime → send  
4.3.2. Implement CLI channel — stdin/stdout  
4.3.3. Implement Web channel — HTTP POST wrapper  
4.3.4. Implement WebSocket channel — streaming  
4.3.5. Propose Flutter channel — optional, personal  
4.3.6. Propose OpenClaw‑style webhook channel — message envelope → runtime  
4.3.7. Document how to build custom channels  
4.3.8. Create FastAPI skeleton  
4.3.9. Add simple HTTP endpoint  
4.3.10. Add WebSocket endpoint  
4.3.11. Implement request → job mapping  
4.3.12. Implement result streaming  
4.3.13. Add auth layer  
4.3.14. Add rate limiting  
4.3.15. Add tracing IDs  
4.3.16. Add health checks  

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
