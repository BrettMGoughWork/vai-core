# PHASE 1 — Core Runtime Foundation (with BaseSkill + ToolSpec)

X. Define core config model — LLM, timeouts, limits, skill paths.  
X. Define ToolSpec class — name, description, schema, side‑effects, category.  
X. Define BaseSkill class — handler, schema generation, validation, execution.  
X. Define skill categories + side‑effect flags — io, network, fs, dangerous.  
X. Implement schema generator — from handler signature → JSON schema.  
X. Implement structural validator — types, required fields.  
X. Implement semantic validator hook — domain‑specific checks.  
8. Implement canonicalisation layer — trim, normalise, lower.  
9. Implement LLM transport wrapper — single entrypoint.  
10. Implement tool selection governance — allowed tools, categories.  
11. Implement tool execution engine — call handler, wrap errors.  
12. Define CoreResult type — success, error, metadata.

---

# PHASE 2 — State Machine & Loop Semantics

13. Define ConversationState — input, history, last tool call, metadata.  
14. Implement corestep(state) — one LLM → tool → result transition.  
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
38. (opinionated custom skill. To remove from official repo) Implement notes skill — CRUD, indexing.  
39. (opinionated custom skill. To remove from official repo) Implement Spotify skill — typed, safe.  
40. (opinionated custom skill. To remove from official repo) Implement Last.fm skill — typed, safe.

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

71. Create FastAPI skeleton  
72. Add simple HTTP endpoint  
73. Add WebSocket endpoint  
74. Define client protocol  
75. Implement request → job mapping  
76. Implement result streaming  
77. Add auth layer  
78. Add rate limiting  
79. Add tracing IDs  
80. Add health checks

---

# PHASE 9 — Agent Runtime (Above the Core Loop)

81. Define AgentSpec — instructions, tools, loop policy.  
82. Implement agent registry  
83. Implement agent context — memory, settings.  
84. Implement agentstep — inject instructions.  
85. Implement agentloop — wraps coreloop.  
86. Add agent permissions  
87. Add agent templates  
88. Add multi‑agent orchestration  
89. Add scheduled agents  
90. Add agent debugging view

---

# PHASE 10 — Resilience, Self‑Healing, Health

91. Classify loop health — healthy, stalled, poisoned.  
92. Detect stalled loops  
93. Auto‑abort stalled loops  
94. Auto‑downgrade behaviour  
95. Add global watchdog  
96. Add auto‑scaling hooks  
97. Add panic reporting  
98. Add resilience tests  
99. Add recovery drills  
100. Document failure modes

---

# PHASE 11 — Observability & Developer Experience

101. Add structured logging  
102. Add metrics exporter  
103. Add tracing spans  
104. Add flamegraph timings  
105. Add local dev CLI  
106. Add replay tooling  
107. Add config inspector  
108. Add skill inspector  
109. Add agent inspector  
110. Add end‑to‑end smoke tests

---

# PHASE 12 — Hardening & Polish

111. Security review of skills  
112. Security review of fetch stack  
113. LLM prompt hardening  
114. Config profiles — dev, prod, paranoid.  
115. Backwards‑compatible APIs  
116. Performance tuning  
117. Load testing  
118. Graceful degradation strategy  
119. Disaster recovery story  
120. Write architecture doc — for future contributors.