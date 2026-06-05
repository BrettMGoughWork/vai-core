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

2.7.1 — Progress Detector ✅
- Compare segment outputs across cycles  
- Detect: steady, stalled, regressed  
- Add progress confidence scoring

2.7.2 — Temporal Drift Signals
- Emit signals for:  
  - no progress  
  - repeated identical outputs  
  - oscillation  
  - regressions

2.7.3 — Temporal Drift Classifier
- Multi‑cycle stall detection  
- Oscillation detection  
- Regressed‑state detection

2.7.4 — Temporal Repair Actions
- Regenerate segment  
- Regenerate plan  
- Re‑decompose subgoal  
- Reset segment state

2.7.5 — Temporal Trace
- Add progress deltas  
- Add stall reasons  
- Add oscillation markers

## PHASE 2.8 — Semantic Reasoner (Meaning, Intent, Goal Alignment)
*Depends On*: PHASE 2.7  
*Goal*: Give Stratum‑2 the ability to detect when behaviour contradicts the plan or subgoal.

2.8.1 — Semantic Validator
- Validate output against step description  
- Validate output against plan intent  
- Validate output against subgoal goal  
- Validate output against memory context

2.8.2 — Semantic Drift Signals
- Emit signals for:  
  - contradicting plan  
  - contradicting subgoal  
  - contradicting memory  
  - contradicting prior behaviour

2.8.3 — Semantic Drift Classifier
- Multi‑signal semantic drift detection  
- Confidence scoring  
- Confirmation logic

2.8.4 — Semantic Repair Actions
- Rewrite step  
- Rewrite segment  
- Rewrite plan  
- Rewrite subgoal

2.8.5 — Semantic Trace
- Add semantic mismatch details  
- Add semantic repair actions  
- Add semantic drift history

## PHASE 2.9 — Full Drift Engine (Unified Drift System)
*Depends On*: PHASE 2.8  
*Goal*: Combine behavioural, temporal, and semantic drift into a unified, governed system.

2.9.1 — Unified Drift Signal Model
- Merge structural, behavioural, temporal, semantic signals  
- Add signal weighting  
- Add signal decay rules

2.9.2 — Unified Drift Classifier
- Multi‑signal classification  
- Confidence scoring  
- Drift severity levels  
- Drift categories: minor, major, catastrophic

2.9.3 — Drift Confirmation Engine
- Multi‑cycle confirmation  
- Confidence accumulation  
- Drift hysteresis (avoid oscillation)

2.9.4 — Drift Recovery Engine
- Choose repair vs replan  
- Choose segment regen vs plan regen  
- Choose subgoal regen vs full reset

2.9.5 — Drift Trace
- Add unified drift history  
- Add drift confidence evolution  
- Add drift recovery decisions

## PHASE 2.10 — Full Repair Engine (Beyond Normalisation)
*Depends On*: PHASE 2.9  
*Goal*: Implement real repair actions, not just structural fixes.

2.10.1 — Repair Action Library
- Fix malformed steps  
- Fix malformed segments  
- Fix malformed plans  
- Fix malformed subgoals  
- Fix drift‑induced inconsistencies

2.10.2 — Repair Budget
- Per‑cycle budget  
- Per‑subgoal budget  
- Per‑plan budget  
- Global budget

2.10.3 — Repair Arbitration
- Decide between:  
  - repair  
  - replan  
  - regenerate segment  
  - regenerate subgoal  
  - escalate to catastrophic drift

2.10.4 — Repair Trace
- Add repair attempts  
- Add repair failures  
- Add repair successes  
- Add repair budget usage

## PHASE 2.11 — Multi‑Segment Reasoner
*Depends On*: PHASE 2.10  
*Goal*: Execute multi‑segment plans with drift/repair/reflection per segment.

2.11.1 — Segment Transition Rules
- pending → active  
- active → complete  
- complete → next segment  
- complete → subgoal complete

2.11.2 — Segment Reflection
- Evaluate progress  
- Evaluate drift  
- Evaluate repair  
- Evaluate completion

2.11.3 — Segment‑Level Drift
- Drift per segment  
- Repair per segment  
- Replan per segment

2.11.4 — Segment Trace
- Add segment transitions  
- Add segment drift  
- Add segment repair  
- Add segment reflection

## PHASE 2.12 — Multi‑Subgoal Reasoner
*Depends On*: PHASE 2.11  
*Goal*: Execute hierarchical plans with multiple subgoals.

2.12.1 — Subgoal Transition Rules
- pending → active  
- active → complete  
- complete → next subgoal  
- complete → agent complete

2.12.2 — Subgoal Reflection
- Evaluate subgoal progress  
- Evaluate subgoal drift  
- Evaluate subgoal repair  
- Evaluate subgoal completion

2.12.3 — Subgoal‑Level Drift
- Drift per subgoal  
- Repair per subgoal  
- Replan per subgoal

2.12.4 — Subgoal Trace
- Add subgoal transitions  
- Add subgoal drift  
- Add subgoal repair  
- Add subgoal reflection

## PHASE 2.13 — Full Agent‑Level Loop v3 (Release‑Ready)
*Depends On*: PHASE 2.12  
*Goal*: The complete hierarchical reasoner required for Stratum‑3.

2.13.1 — Full Agent Loop
- Multi‑subgoal  
- Multi‑segment  
- Multi‑cycle  
- Drift‑aware  
- Repair‑aware  
- Reflection‑aware  
- Memory‑aware

2.13.2 — Full Error Handling
- catastrophic drift  
- catastrophic repair failure  
- invalid memory state  
- invalid subgoal state  
- invalid segment state

2.13.3 — Full Trace
- agent trace  
- subgoal trace  
- segment trace  
- drift trace  
- repair trace  
- reflection trace  
- memory trace

2.13.4 — Release 1 Validation
- determinism tests  
- drift tests  
- repair tests  
- multi‑segment tests  
- multi‑subgoal tests  
- long‑horizon tests 

---
🚀 Release 1 — "Hierarchical Reasoner"
---

## STRATUM 3 - Agent Runtime
*Invariant*: Stratum 3 orchestrates agents, capabilities and external intefaces, but never performs long-horizion reasoning planning, and execution itself. It delegates all reasoning to Stratum 2 and all action execution to Stratum 1

### PHASE 3.1 — Skill & Capability Layer (Core Skill)
*Depends On*: PHASE 2.5  
*Note:: Stratum 3 requires the full hierarchical reasoner to ensure agent-level planning is stable

3.1.1. Implement skill registry — register skills, metadata, ToolSpecs.  
3.1.2. Add permission model — allow/deny categories per agent/runtime.  
3.1.3. Implement filesystem skill — safe paths, locking.  
3.1.4. Implement HTTP simple skill — allowlist, limits.  
3.1.5. Implement math utilities — parse, convert.  
3.1.6. Implement text utilities — split, regex.  

---
🚀 Release 2 — "Skillful Agent"
---

### PHASE 3.2 — Skill & Capability Layer (Extension Skills)
*Depends On*: PHASE 3.1

3.2.1. Define plugin interface — simple Python module exposing register_all()  
3.2.2. Implement plugin loader — load skills from external repos  
3.2.3. Document how to build personal plugins (e.g., vai‑extensions)  

---
🚀 Release 3 — "Extensible Agent"
---

### PHASE 3.3a — Fetch Orchestrator
*Depends On*: PHASE 3.2

3.3.1. Define FetchError taxonomy  
3.3.2. Define fetchurl skill interface — url, mode="auto".    
3.3.3. Implement simple httpx fetch — fast, strict.    
3.3.4. Implement hardened HTTP (CRW) — anti‑bot header (opinionated).    
3.3.5. Implement Playwright headless — JS rendering (opinionated)    
3.3.6. Implement Playwright stealth — heavy, rate‑limited (opnionated)  
3.3.7. Implement search — query → URLs (see 3.3b search provider)  
3.3.8. Implement fetch heuristics — escalation logic.    
3.3.9. Implement fallback chain — simple → hardened → browser → stealth → search.    
3.3.10. Add per‑domain policy — allowlists, rate limits.    
3.3.11. Expose only fetch_url to LLM — hide internal strategies.  

---

### PHASE 3.3b - Search Provider
*Depends On*: PHASE 3.2 (Note: this may need to swap with fetch orchestrator phase)

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

3.8.1. Classify loop health — healthy, stalled, poisoned.  
3.8.2. Detect stalled loops  
3.8.3. Auto‑abort stalled loops  
3.8.4. Auto‑downgrade behaviour  
3.8.5. Add global watchdog  
3.8.6. Add auto‑scaling hooks  
3.8.7. Add panic reporting  
3.8.8. Add resilience tests  
3.8.9. Add recovery drills  
3.8.10. Document failure modes

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
