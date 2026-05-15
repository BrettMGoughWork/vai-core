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
15. Classify step outcomes — success, recoverable, fatal, noop.  
16. Define isdone(state) — goal reached, limits hit.  
17. Implement coreloop(state, policy) — while not done → step.  
18. Define loop policy model — max steps, wall time, errors.  
19. Add per‑step timeout — kill slow steps.  
20. Add per‑loop timeout — kill runaway loops.  
21. Add loop trace log — append step summaries.

---

# PHASE 3 — Error Model, Retries, Resilience

22. Define error taxonomy — LLMError, ToolError, ValidationError, SystemError.  
23. Implement retry policy — per error type.  
24. Add LLM retry wrapper — transient network/timeouts.  
25. Add tool retry wrapper — idempotent tools only.  
26. Add circuit breaker per tool — stop repeated failures.  
27. Add degraded mode — fallback to simpler behaviour.  
28. Add safe failure response — structured error.  
29. Add panic guard — catch unexpected exceptions.  
30. Add loop self‑healing — adjust state, continue.  
31. Detect poison jobs — mark unrecoverable inputs.

---

# PHASE 4 — Skill & Capability Layer

32. Implement skill registry — register skills, metadata, ToolSpecs.  
33. Add permission model — allow/deny categories per agent/runtime.  
34. Implement filesystem skill — safe paths, locking.  
35. Implement HTTP simple skill — allowlist, limits.  
36. Implement math utilities — parse, convert.  
37. Implement text utilities — split, regex.  
38. Define plugin interface — simple Python module exposing register_all()  
39. Implement plugin loader — load skills from external repos  
40. Document how to build personal plugins (e.g., vai‑personal)  

---

# PHASE 5 — Fetch Orchestrator

41. Define fetchurl skill interface — url, mode="auto".  
42. Implement simple httpx fetch — fast, strict.  
43. Implement hardened HTTP (CRW) — anti‑bot headers.  
44. Implement Playwright headless — JS rendering.  
45. Implement Playwright stealth — heavy, rate‑limited.  
46. Implement Tavily search — query → URLs.  
47. Implement fetch heuristics — escalation logic.  
48. Implement fallback chain — simple → hardened → browser → stealth → search.  
49. Add per‑domain policy — allowlists, rate limits.  
50. Expose only fetch_url to LLM — hide internal strategies.

---

# PHASE 6 — Queue & Job Model

51. Choose queue backend — Redis/SQLite.  
52. Define Job envelope — id, payload, metadata.  
53. Define JobResult envelope — status, result, error.  
54. Implement enqueue API  
55. Implement dequeue API  
56. Implement result store  
57. Add dead‑letter queue  
58. Add queue metrics  
59. Add priority queues  
60. Add backpressure handling

---

# PHASE 7 — Worker Pool & Supervision

61. Implement worker entrypoint — dequeue → core_loop → store result.  
62. Add worker config — concurrency, queues, limits.  
63. Add worker telemetry  
64. Add worker heartbeat  
65. Implement worker supervisor — restart on crash.  
66. Add graceful shutdown  
67. Add worker circuit breaker  
68. Add job cancellation  
69. Add job timeouts  
70. Add heavy‑skill worker pool — browser/stealth.

---

# PHASE 8 — FastAPI & WebSocket Layer

71. Define Channel interface — receive → runtime → send  
72. Implement CLI channel — stdin/stdout  
73. Implement Web channel — HTTP POST wrapper  
74. Implement WebSocket channel — streaming  
75. Propose Flutter channel — optional, personal  
76. Propose OpenClaw‑style webhook channel — message envelope → runtime  
77. Document how to build custom channels  
Existing FastAPI/WebSocket tasks
78. Create FastAPI skeleton  
79. Add simple HTTP endpoint  
80. Add WebSocket endpoint  
81. Implement request → job mapping  
82. Implement result streaming  
83. Add auth layer  
84. Add rate limiting  
85. Add tracing IDs  
86. Add health checks  

---

# PHASE 9 — Agent Runtime (Above the Core Loop)

87. Define AgentSpec — instructions, tools, loop policy.  
88. Implement agent registry  
89. Implement agent context — memory, settings.  
90. Implement agentstep — inject instructions.  
91. Implement agentloop — wraps coreloop.  
92. Add agent permissions  
93. Add agent templates  
94. Add multi‑agent orchestration  
95. Add scheduled agents  
96. Add agent debugging view

---

# PHASE 10 — Resilience, Self‑Healing, Health

97. Classify loop health — healthy, stalled, poisoned.  
98. Detect stalled loops  
99. Auto‑abort stalled loops  
100. Auto‑downgrade behaviour  
101. Add global watchdog  
102. Add auto‑scaling hooks  
103. Add panic reporting  
104. Add resilience tests  
105. Add recovery drills  
106. Document failure modes

---

# PHASE 11 — Observability & Developer Experience

107. Add structured logging  
108. Add metrics exporter  
109. Add tracing spans  
110. Add flamegraph timings  
111. Add local dev CLI  
112. Add replay tooling  
113. Add config inspector  
114. Add skill inspector  
115. Add agent inspector  
116. Add end‑to‑end smoke tests

---

# PHASE 12 — Hardening & Polish

117. Security review of skills  
118. Security review of fetch stack  
119. LLM prompt hardening  
120. Config profiles — dev, prod, paranoid.  
121. Backwards‑compatible APIs  
122. Performance tuning  
123. Load testing  
124. Graceful degradation strategy  
125. Disaster recovery story  
126. Write architecture doc — for future contributors.