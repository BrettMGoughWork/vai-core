## STRATUM 1 - Execution Substrate
*Invariant*: Stratum 1 must remain deterministic, reactive, and free of long-horizon reasoning

# PHASE 1.1 — Core Runtime Foundation (with BaseSkill + ToolSpec)

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

# PHASE 1.2 — State Machine & Loop Semantics
*Depends On*: PHASE 1.1

✅ 1.2.1. Define ConversationState — input, history, last tool call, metadata.  
✅ 1.2.2. Implement corestep(state) — one LLM → tool → result transition.  
✅ 1.2.3. Classify step outcomes — success, recoverable, fatal, noop.  
✅ 1.2.4. Define isdone(state) — goal reached, limits hit.  
✅ 1.2.5. Implement coreloop(state, policy) — while not done → step.  
✅ 1.2.6. Define loop policy model — max steps, wall time, errors.  
✅ 1.2.7. Add per‑step timeout — kill slow steps.  
✅ 1.2.8. Add per‑loop timeout — kill runaway loops.  
✅ 1.2.9. Add loop trace log — append step summaries.

---

# PHASE 1.3 - Execution Semantics
*Depends On*: PHASE 1.2

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

# PHASE 1.4 — Error Model, Retries, Resilience
*Depends On*: PHASE 3

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
✅ 1.4.11. CLI helper that prints the plan (python3 main.py agent plan)
✅ 1.4.12. Bug fixes leading to stable Release 0 

---
🚀 Release 0 — "The Substrate"
---

## STRATUM 2 - Hierarchical Intelligence
*Invariant*: Stratum 2 must be pure: no side effects, no tool calls, no LLM calls. It only produces subgoals and plan segments for Stratum 1 to execute.

# PHASE 2.1 - Multi-Step Loop Foundation
*Depends on*: PHASE 1.4  
2.1.1. Step State - the per-state state container  
2.1.2. Step Result - the structured output of each step  
2.1.3. Multi-Step Core - CoreStep v2  
2.1.4. Loop Policy - max steps, timeouts, etc  
2.1.5. Step Outcome Classifier - LLM model that says continue|stop|tool needed|error  
2.1.6. Loop Orchestrator - deterministic loop controller  

# PHASE 2.2 - Flat Planner (non-hierarchical)
*Depends on*: PHASE 2.1  
2.2.1. Plan Generator - LLM generates a list of steps  
2.2.2. Plan Validator - ensures the plan is safe  
2.2.3. Plan Executor - executes steps sequentially  
2.2.4. Plan State - tracks progress  
2.2.5. Plan Repair - minimal repair rules  
2.2.6. Plan Execution Safety Layer  

# PHASE 2.3 - Hierarchical planning
*Depends On*: PHASE 2.2  
2.3.1. Define Subgoal model  
2.3.2. Define PlanSegment model   
2.3.3. Implement Subgoal Manager  
2.3.4. Implement Plan Manager  
2.3.5. Add Governed Signals  
2.3.6. Add Subgoal/Segment State to ConversationState    
2.3.7. Implement Agent-level loop (agentloop v2)    
2.3.8. Define Subgoal Transition Rules    
2.3.9. Define Drift Detection Model    
2.3.10. Subgoal Validation Rules    

# PHASE 2.4 - Memory Model v1
*Depends On*: PHASE 2.3  
2.4.1. Subgoal memory  
2.4.2. Segment memory  
2.4.3. Plan memory  
2.4.4. Drift memory (plan divergence)  

---
🚀 Release 1 — "Hierarchical Reasoner"
---

## STRATUM 3 - Agent Runtime
*Invariant*: Stratum 3 orchestrates agents, capabilities and external intefaces, but never performs long-horizion reasoning planning, and execution itself. It delegates all reasoning to Stratum 2 and all action execution to Stratum 1

# PHASE 3.1 — Skill & Capability Layer (Core Skill)
*Depends On*: PHASE 2.3

3.1.1. Implement skill registry — register skills, metadata, ToolSpecs.  
3.1.2. Add permission model — allow/deny categories per agent/runtime.  
3.1.3. Implement filesystem skill — safe paths, locking.  
3.1.4. Implement HTTP simple skill — allowlist, limits.  
3.1.5. Implement math utilities — parse, convert.  
3.1.6. Implement text utilities — split, regex.  

---
🚀 Release 2 — "Skillful Agent"
---

# PHASE 3.2 — Skill & Capability Layer (Extension Skills)
*Depends On*: PHASE 3.1

3.2.1. Define plugin interface — simple Python module exposing register_all()  
3.2.2. Implement plugin loader — load skills from external repos  
3.2.3. Document how to build personal plugins (e.g., vai‑extensions)  

---
🚀 Release 3 — "Extensible Agent"
---

# PHASE 3.3 — Fetch Orchestrator
*Depends On*: PHASE 3.2

3.3.1. Define FetchError taxonomy  
3.3.2. Define fetchurl skill interface — url, mode="auto".    
3.3.3. Implement simple httpx fetch — fast, strict.    
3.3.4. Implement hardened HTTP (CRW) — anti‑bot header (opinionated?).    
3.3.5. Implement Playwright headless — JS rendering (opinionated?)    
3.3.6. Implement Playwright stealth — heavy, rate‑limited (opnionated?)  
3.3.7. Implement Tavily search — query → URLs (opinionated ($), so may require a separate phase for search providers)  
3.3.8. Implement fetch heuristics — escalation logic.    
3.3.9. Implement fallback chain — simple → hardened → browser → stealth → search.    
3.3.10. Add per‑domain policy — allowlists, rate limits.    
3.3.11. Expose only fetch_url to LLM — hide internal strategies.  

---

# PHASE 3.4 — Queue & Job Model
*Depends On*: PHASE 3.3

3.4.1. Choose queue backend — Redis/SQLite.  
3.4.2. Define Job envelope — id, payload, metadata.  
3.4.3. Define JobResult envelope — status, result, error.  
3.4.4. Implement enqueue API  
3.4.5. Implement dequeue API  
3.4.6. Implement result store  
3.4.7. Add dead‑letter queue  
3.4.8. Add queue metrics  
3.4.9. Add priority queues  
3.4.10. Add backpressure handling

---
🚀 Release 4 — "Distributed Agent Runtime"
---

# PHASE 3.5 — Worker Pool & Supervision
*Depends On*: PHASE 3.4

3.5.1. Implement worker entrypoint — dequeue → core_loop → store result.  
3.5.2. Add worker config — concurrency, queues, limits.  
3.5.3. Add worker telemetry  
3.5.4. Add worker heartbeat  
3.5.5. Implement worker supervisor — restart on crash.  
3.5.6. Add graceful shutdown  
3.5.7. Add worker circuit breaker  
3.5.8. Add job cancellation  
3.5.9. Add job timeouts  
3.5.10. Add heavy‑skill worker pool — browser/stealth.

---
🚀 Release 5 — "API-Driven Agent Platform"
---

# PHASE 3.6 — FastAPI & WebSocket Layer
*Depends On*: PHASE 3.5

3.6.1. Define Channel interface — receive → runtime → send  
3.6.2. Implement CLI channel — stdin/stdout  
3.6.3. Implement Web channel — HTTP POST wrapper  
3.6.4. Implement WebSocket channel — streaming  
3.6.5. Propose Flutter channel — optional, personal  
3.6.6. Propose OpenClaw‑style webhook channel — message envelope → runtime  
3.6.7. Document how to build custom channels  
3.6.8. Create FastAPI skeleton  
3.6.9. Add simple HTTP endpoint  
3.6.10. Add WebSocket endpoint  
3.6.11. Implement request → job mapping  
3.6.12. Implement result streaming  
3.6.13. Add auth layer  
3.6.14. Add rate limiting  
3.6.15. Add tracing IDs  
3.6.16. Add health checks  

---
🚀 Release 6 — "Multi-Agent System"
---

# PHASE 3.7 — Agent Runtime (Above the Core Loop)
*Depends On*: PHASE 3.6

3.7.1. Define AgentSpec — instructions, tools, loop policy.  
3.7.2. Implement agent registry  
3.7.3. Implement agent context — memory, settings.  
3.7.4. Implement agentstep — inject instructions.  
3.7.5. Implement agentloop — wraps coreloop.  
3.7.6. Add agent permissions  
3.7.7. Add agent templates  
3.7.8. Add multi‑agent orchestration  
3.7.9. Add scheduled agents  
3.7.10. Add agent debugging view
3.7.11. Agent Memory Model
3.7.12. Agent Identity & Persona Model
3.7.13. Agent Capability Graph

---

# PHASE 3.8 — Resilience, Self‑Healing, Health
*Depends On*: PHASE 3.7

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

# PHASE 3.9 — Observability & Developer Experience
*Depends On*: PHASE 3.8

3.9.1. Add structured logging  
3.9.2. Add metrics exporter  
3.9.3. Add tracing spans  
3.9.4. Add flamegraph timings  
3.9.5. Add local dev CLI  
3.9.6. Add replay tooling  
3.9.7. Add config inspector  
3.9.8. Add skill inspector  
3.9.9. Add agent inspector  
3.9.10. Add end‑to‑end smoke tests

---
🚀 Release 8 — "Observable and Developer-Friendly Runtime"
---

# PHASE 3.10 — Hardening & Polish
*Depends On*: PHASE 3.9

3.10.1. Security review of skills  
3.10.2. Security review of fetch stack  
3.10.3. LLM prompt hardening  
3.10.4. Config profiles — dev, prod, paranoid.  
3.10.5. Backwards‑compatible APIs  
3.10.6. Performance tuning  
3.10.7. Load testing  
3.10.8. Graceful degradation strategy  
3.10.9. Disaster recovery story  
3.10.10. Write architecture doc — for future contributors.

---
🚀 Release 9 — "Hardened Runtime"
---

## STRATUM 4 - Cognitive Systems and Meta-Agents

# PHASE 4.1 - Meta-Planning and Self-Reflection

# PHASE 4.2 - Long-Term Memory and Knowledge Graphs

# PHASE 4.3 - Multi-Agent Societies

# PHASE 4.4 - Tool Learning and Skill Synthesis

# PHASE 4.5 - Autonomy and Governance

---
