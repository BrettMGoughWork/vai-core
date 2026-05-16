# PHASE 1 — Core Runtime Foundation (with BaseSkill + ToolSpec)

X. Define core config model — LLM, timeouts, limits, skill paths.  
X. Define ToolSpec class — name, description, schema, side‑effects, category.  
X. Define BaseSkill class — handler, schema generation, validation, execution.  
X. Define skill categories + side‑effect flags — io, network, fs, dangerous.  
X. Implement schema generator — from handler signature → JSON schema.  
X. Implement structural validator — types, required fields.  
X. Implement semantic validator hook — domain‑specific checks.  
X. Implement canonicalisation layer — trim, normalise, lower.  
X. Implement LLM transport wrapper — single entrypoint.  
X. Implement tool selection governance — allowed tools, categories.  
X. Implement tool execution engine — call handler, wrap errors.  
X. Define CoreResult type — success, error, metadata.

---

# PHASE 2 — State Machine & Loop Semantics

X. Define ConversationState — input, history, last tool call, metadata.  
X. Implement corestep(state) — one LLM → tool → result transition.  
X. Classify step outcomes — success, recoverable, fatal, noop.  
X. Define isdone(state) — goal reached, limits hit.  
X. Implement coreloop(state, policy) — while not done → step.  
X. Define loop policy model — max steps, wall time, errors.  
X. Add per‑step timeout — kill slow steps.  
X. Add per‑loop timeout — kill runaway loops.  
X. Add loop trace log — append step summaries.

---

# PHASE 2.1 - Core Intelligence implementation

X. Plan Schema
23. Local Planner
X. Plan Validation
X. Skill Metadata
26. Skill Filtering
27. Skill Ranking
X. Executor Contract
29. Single-Skill Execution
30. Error Types
31. CoreStep Pipeline
32. Logging
33. Unit Tests
34. Integration Tests

---

# PHASE 3 — Error Model, Retries, Resilience

35. Define error taxonomy — LLMError, ToolError, ValidationError, SystemError.  
36. Implement retry policy — per error type.  
37. Add LLM retry wrapper — transient network/timeouts.  
38. Add tool retry wrapper — idempotent tools only.  
39. Add circuit breaker per tool — stop repeated failures.  
40. Add degraded mode — fallback to simpler behaviour.      
41. Add safe failure response — structured error.  
42. Add panic guard — catch unexpected exceptions.  
43. Add loop self‑healing — adjust state, continue.  
44. Detect poison jobs — mark unrecoverable inputs.

---

# PHASE 4 — Skill & Capability Layer

45. Implement skill registry — register skills, metadata, ToolSpecs.  
46. Add permission model — allow/deny categories per agent/runtime.  
47. Implement filesystem skill — safe paths, locking.  
48. Implement HTTP simple skill — allowlist, limits.  
49. Implement math utilities — parse, convert.  
50. Implement text utilities — split, regex.  
51. Define plugin interface — simple Python module exposing register_all()  
52. Implement plugin loader — load skills from external repos  
53. Document how to build personal plugins (e.g., vai‑personal)  

---

# PHASE 5 — Fetch Orchestrator

54. Define fetchurl skill interface — url, mode="auto".  
55. Implement simple httpx fetch — fast, strict.  
56. Implement hardened HTTP (CRW) — anti‑bot headers.  
57. Implement Playwright headless — JS rendering.  
58. Implement Playwright stealth — heavy, rate‑limited.  
59. Implement Tavily search — query → URLs.  
60. Implement fetch heuristics — escalation logic.  
61. Implement fallback chain — simple → hardened → browser → stealth → search.  
62. Add per‑domain policy — allowlists, rate limits.  
63. Expose only fetch_url to LLM — hide internal strategies.

---

# PHASE 6 — Queue & Job Model

64. Choose queue backend — Redis/SQLite.  
65. Define Job envelope — id, payload, metadata.  
66. Define JobResult envelope — status, result, error.  
67. Implement enqueue API  
68. Implement dequeue API  
69. Implement result store  
70. Add dead‑letter queue  
71. Add queue metrics  
72. Add priority queues  
73. Add backpressure handling

---

# PHASE 7 — Worker Pool & Supervision

74. Implement worker entrypoint — dequeue → core_loop → store result.  
75. Add worker config — concurrency, queues, limits.  
76. Add worker telemetry  
77. Add worker heartbeat  
78. Implement worker supervisor — restart on crash.  
79. Add graceful shutdown  
80. Add worker circuit breaker  
81. Add job cancellation  
82. Add job timeouts  
83. Add heavy‑skill worker pool — browser/stealth.

---

# PHASE 8 — FastAPI & WebSocket Layer

84. Define Channel interface — receive → runtime → send  
85. Implement CLI channel — stdin/stdout  
86. Implement Web channel — HTTP POST wrapper  
87. Implement WebSocket channel — streaming  
88. Propose Flutter channel — optional, personal  
89. Propose OpenClaw‑style webhook channel — message envelope → runtime  
90. Document how to build custom channels  
91. Create FastAPI skeleton  
92. Add simple HTTP endpoint  
93. Add WebSocket endpoint  
94. Implement request → job mapping  
95. Implement result streaming  
96. Add auth layer  
97. Add rate limiting  
98. Add tracing IDs  
99. Add health checks  

---

# PHASE 9 — Agent Runtime (Above the Core Loop)

100. Define AgentSpec — instructions, tools, loop policy.  
101. Implement agent registry  
102. Implement agent context — memory, settings.  
103. Implement agentstep — inject instructions.  
104. Implement agentloop — wraps coreloop.  
105. Add agent permissions  
106. Add agent templates  
107. Add multi‑agent orchestration  
108. Add scheduled agents  
109. Add agent debugging view

---

# PHASE 10 — Resilience, Self‑Healing, Health

110. Classify loop health — healthy, stalled, poisoned.  
111. Detect stalled loops  
112. Auto‑abort stalled loops  
113. Auto‑downgrade behaviour  
114. Add global watchdog  
115. Add auto‑scaling hooks  
116. Add panic reporting  
117. Add resilience tests  
118. Add recovery drills  
119. Document failure modes

---

# PHASE 11 — Observability & Developer Experience

120. Add structured logging  
121. Add metrics exporter  
122. Add tracing spans  
123. Add flamegraph timings  
124. Add local dev CLI  
125. Add replay tooling  
126. Add config inspector  
127. Add skill inspector  
128. Add agent inspector  
129. Add end‑to‑end smoke tests

---

# PHASE 12 — Hardening & Polish

130. Security review of skills  
131. Security review of fetch stack  
132. LLM prompt hardening  
133. Config profiles — dev, prod, paranoid.  
134. Backwards‑compatible APIs  
135. Performance tuning  
136. Load testing  
137. Graceful degradation strategy  
138. Disaster recovery story  
139. Write architecture doc — for future contributors.