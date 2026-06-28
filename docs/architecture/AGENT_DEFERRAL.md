# Agent Deferral

> **Status:** Draft plan  
> **Roadmap:** Sprint D1 — Agent Deferral  
> **Created:** 2026-06-21

## Concept

Agent deferral lets an agent hand off work to another agent at runtime. The delegating agent suspends, the delegate runs with its own persona and tools, and the delegating agent resumes with the delegate's response. The deferral graph must be **acyclic** — enforced at registration time.

This is not a general-purpose routing mechanism. It is a pattern for specific use cases where one agent recognises that another is better suited to the task at hand.

## Use Cases

### Specialisation (Domain Expertise)
A general support agent detects a billing-related query and hands off to a billing specialist. A research agent gathers sources then defers to a fact-checker for validation. A coding agent writes code then defers to a security reviewer for audit.

### Capability Mismatch
A general-purpose chat assistant with minimal tools detects a task requiring capabilities it doesn't have. Instead of failing, it defers to a specialist agent that has the right tools. This keeps the chat assistant "dumb" while still being useful as a router.

### Task Decomposition (Sub-Agents)
A product launch orchestrator defers sub-tasks to marketing, QA, and engineering agents. Each sub-agent handles its domain independently and returns results. This can run sequentially or in parallel (future).

### Multi-Perspective Reasoning
Opens the door to council-based deliberation — multiple agents analyze the same problem from different angles, then a lead agent synthesises their outputs. This is a future Y-horizon feature; deferral provides the primitive.

## Design

### Data Model

```yaml
# config/agents/support-agent.yaml
agent_id: support-agent
name: General Support
defer_to:
  - billing-agent
  - technical-agent
tools: [knowledge_search]
patterns: [triage_inbox]
```

`defer_to` is an **optional** list of agent IDs. If empty or omitted, the agent cannot defer. If populated, the agent can hand off work to any listed peer.

### Acyclicity Enforcement

At registration time, the registry validates that the deferral graph has no cycles. This runs once at startup — no runtime overhead.

**Algorithm:**
1. Build a directed graph from all registered agents: node A → node B if B is in A's `defer_to` list.
2. Run DFS cycle detection on the full graph.
3. On cycle found: raise `DeferralCycleError` listing the cycle path (e.g., `"support-agent → billing-agent → support-agent"`).

**Why registration-time?** The registry is built once at startup. Deferral graphs are small (typically < 50 nodes). DFS is O(V+E). No runtime cost.

**What about dynamic agents?** Agents defined in local overlay (`config/local/`) that defer to built-in agents are validated at the same time — the full graph exists before any agent is activated.

### Hand-Off Model: Suspend → Delegate → Resume

```
Delegating Agent (support-agent)
    │
    │  "I think this is a billing question. Let me hand it off."
    │
    ├── defer_to(target="billing-agent", prompt="User is asking about an overcharge on invoice #1234...")
    │
    │  ┌─ Supervisor: suspend support-agent
    │  │    ├── Save conversation state
    │  │    └── Mark as SUSPENDED_DEFERRED
    │  │
    │  ├─ Supervisor: activate billing-agent
    │  │    ├── Build activation context with prompt from delegator
    │  │    ├── billing-agent's persona: "You are a billing specialist..."
    │  │    ├── billing-agent's tools: [invoice_lookup, refund_process, ...]
    │  │    └── Run billing-agent to completion
    │  │
    │  └─ Supervisor: resume support-agent
    │       ├── Inject delegate response into conversation history
    │       ├── Mark as RUNNING
    │       └── support-agent continues: "The billing agent found the issue..."
    │
    ▼
  Final response to user
```

**Key properties:**
- The delegate runs with **its own persona, tools, and patterns** — not the caller's.
- The delegate's **full conversation** (prompt → tool calls → response) is injected back into the caller's history.
- The caller resumes at the point it left off, with the delegate's output available as context.
- Only one agent is active at a time (single-threaded deferral; parallel sub-agents are future work).

### Intent Routing

How does an agent decide *which* agent to defer to?

**Option A — LLM-driven (initial approach):**
The agent's persona lists available deferral targets and when to use each. The LLM decides at runtime.

```yaml
persona: |
  You are a general support agent.
  
  You can defer to specialist agents:
  - billing-agent: for payment, invoice, or refund questions
  - technical-agent: for bug reports, outages, or API questions
  
  When you detect a query matching one of these domains, use the defer_to tool
  to hand off to the right specialist. Include full context so they don't need
  to re-ask the user anything.
```

The `defer_to` tool is surfaced to the LLM like any other tool:

```json
{
  "name": "defer_to",
  "description": "Hand off the current task to another agent. Use when a specialist agent is better suited.",
  "parameters": {
    "target": "The agent_id to defer to (must be one of: billing-agent, technical-agent)",
    "prompt": "Full context and instructions for the target agent"
  }
}
```

**Option B — Deterministic routing (future):**
Keywords, regex patterns, or embedding similarity could auto-route without an LLM decision. This is more predictable but less flexible. Out of scope for D1.

### Depth Guard

Even with an acyclic graph, a chain like A→B→C→D→E could produce excessive context bloat. A configurable `max_deferral_depth` (default: 3) caps the chain length:

```
support-agent → billing-agent → refund-agent  ✓ (depth 2, under limit)
support-agent → billing-agent → refund-agent → audit-agent  ✗ (depth 3, hits limit)
```

The depth counter is tracked in the agent state and passed through each deferral. Exceeding it raises `DeferralDepthError`.

## Concerns & Mitigations

| Concern | Mitigation |
|---------|------------|
| **Context blow-up** — each deferral appends the full delegate conversation. After 3 defers, the original agent's context could be enormous. | Summarise delegate responses before injecting them back. The context bridge can compress the delegate's output into a short summary + key findings. Configurable per agent. |
| **Tool isolation** — if the delegating agent defers because it lacks tools, the delegate must actually have those tools. If not, the chain fails. | Validation warning at registration: if agent A defers to B for reason X, but B doesn't have tools related to X, log a warning. Not a hard error — the LLM might still handle it. |
| **Infinite loops via workflows/patterns** — agent A defers to B, B runs a workflow that invokes agent A. | The acyclicity check catches direct deferral cycles. Workflow-level loops need a separate guard — track visited agent IDs per invocation chain and reject re-entry. Out of scope for D1 but documented as a known risk. |
| **Starvation** — a delegating agent defers to a specialist that never returns (infinite loop, stuck tool call). | The delegate runs under the same Supervisor with the same timeout/max_iterations constraints. If the delegate exceeds its constraints, it fails and the delegating agent resumes with an error. |
| **Ambiguous hand-off** — the LLM defers but doesn't provide enough context for the delegate to work. | The delegate can ask clarifying questions via user_input (if the channel supports it) or fail gracefully. The delegating agent sees the delegate's response and can retry with more context. |
| **Registration ordering** — agent A's config references agent B, but B hasn't been loaded yet. | Load all agent configs into a pending list first, validate the full graph, then register. Two-pass loading: (1) parse all YAML into metadata objects, (2) validate the deferral graph, (3) register all. |

## Implementation Path

### Phase 1 — Data Model & Validation (D1.1–D1.3)
Add `defer_to` to `AgentMetadata`. Implement the acyclicity validator. Update the YAML loader. These are pure registry changes — no runtime behaviour yet.

### Phase 2 — Runtime Hand-Off (D1.4–D1.7)
Build the deferral resolver, context bridge, and Supervisor integration. The `defer_to_agent()` method on Supervisor orchestrates the full suspend → delegate → resume lifecycle.

### Phase 3 — LLM Integration (D1.8)
Expose `defer_to` as a tool so LLMs can invoke it. This is where agent personas get the ability to decide *when* and *to whom* to defer.

### Phase 4 — Testing & Hardening (D1.9–D1.14)
Cycle detection edge cases, hand-off/back integration tests, depth limits, tool isolation.

## Future Directions

- **Parallel sub-agents** — defer to multiple agents concurrently and merge results. Requires a fan-out/fan-in pattern in the Supervisor.
- **Council deliberation** — multiple agents analyze the same prompt independently, then a lead agent synthesises. Builds on parallel sub-agents.
- **Deferral chains with mid-chain HITL** — a delegate pauses for user input, the user responds, the delegate continues, then hands back. Already supported by the existing HITL infrastructure.
- **Deferral analytics** — track which agents defer to which, success rates, average chain depth. Feeds into the emergent codification engine (Y.8).
- **Dynamic deferral discovery** — agents discover available delegates at runtime rather than having them hard-coded. Requires a capability registry that agents can query.
