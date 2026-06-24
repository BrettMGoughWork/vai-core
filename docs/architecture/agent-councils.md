# Agent Councils

> **Status:** Implemented (C1)  
> **Roadmap:** C1 — Council Arbitration  
> **Created:** 2026-06-24

## Concept

An **agent council** is a multi-agent deliberation pattern where a panel of specialist agents independently analyse a problem, critique each other's positions, and an impartial arbitrator synthesises a final decision. Each member contributes from its own persona — architect, product manager, engineer, etc. — while the arbitrator weighs all perspectives and produces a structured outcome.

This builds on the [Agent Deferral](agent-deferral.md) primitive: the council orchestrator uses `supervisor.defer_to_agent()` to run each member in turn, collecting their responses before moving to the next phase.

## Deliberation Lifecycle

A council deliberation runs through four phases:

```
              ┌──────────────┐
              │   Problem    │
              │  Statement   │
              └──────┬───────┘
                     │
                     ▼
    ┌────────────────────────────┐
    │  Phase 1: Analysis         │  Each member analyses independently
    │  (all members in parallel) │  from its own persona
    └────────────────────────────┘
                     │
                     ▼
    ┌────────────────────────────┐
    │  Phase 2: Counter-Analysis │  Each member reviews and critiques
    │  (all members in parallel) │  the other members' analyses
    └────────────────────────────┘
                     │
                     ▼
    ┌────────────────────────────┐
    │  Phase 3: Arbitration      │  Arbitrator synthesises all
    │  (arbitrator only)         │  perspectives into a decision
    └────────────────────────────┘
                     │
                     ▼
    ┌────────────────────────────┐
    │  Phase 4: Hand-back        │  Structured outcome returned
    │  (to calling agent/user)   │  to the caller
    └────────────────────────────┘
```

### Phase 1 — Analysis

Each council member receives the problem statement and produces an independent analysis from its own perspective. Members do **not** see each other's analyses at this stage. The prompt asks for:

- **Analysis** — reasoning from the member's domain
- **Recommendation** — proposed course of action
- **Assumptions** — key assumptions underlying the analysis
- **Risks** — identified risks

### Phase 2 — Counter-Analysis

Each member receives the **other** members' analyses (their own analysis is excluded) and is asked to engage critically:

- Points they agree with and why
- Flaws or gaps they identify
- Overlooked considerations
- How their perspective differs

### Phase 3 — Arbitration

The arbitrator receives **all** analyses and counter-analyses and produces a structured decision:

```
Decision: <clear statement of the decision>
Rationale: <reasoning referencing key points>
Confidence: <HIGH | MEDIUM | LOW>
Dissent Notes: <any minority opinions or concerns>
```

### Phase 4 — Hand-back

The structured `CouncilOutcome` (decision, confidence, member analyses, counter-analyses, dissent notes) is returned to the caller — either the user directly (via `/council` command) or a calling agent that invoked the council via workflow.

## Councils

### Dev Squad

`/council dev-squad on "<problem>"`

Five perspectives mirroring a cross-functional product team:

| Member | Role |
|--------|------|
| `architect` | System design, scalability, maintainability, tech debt |
| `product-manager` | Business value, user needs, market fit, priorities |
| `software-engineer` | Implementation feasibility, code-level concerns, effort |
| `quality-analyst` | Testing, edge cases, non-functional requirements |
| `delivery-lead` | Timeline, dependencies, risk to shipping |

Arbitrator: `tech-lead-adjudicator` — synthesises all five perspectives into an actionable technical decision.

### General Nominal

`/council general-nominal on "<problem>"`

A lighter three-member council for broader decisions:

| Member | Role |
|--------|------|
| `strategist` | Big-picture, long-term implications, alignment |
| `critic` | Devil's advocate, identifying flaws and blind spots |
| `risk-assessor` | Risk analysis, probability, impact, mitigation |

Arbitrator: `balanced-adjudicator` — weighs strategic, critical, and risk perspectives.

## Configuration

### Council Definition

Councils are defined in `config/councils/*.yaml`:

```yaml
# config/councils/dev-squad.yaml
council_id: dev-squad
name: "Dev Squad Council"
description: "..."
arbitrator_agent_id: tech-lead-adjudicator
member_agent_ids:
  - architect
  - product-manager
  - software-engineer
  - quality-analyst
  - delivery-lead
max_analysis_tokens: 2000
max_counter_tokens: 1500
require_consensus: false
```

### Member Agents

Council members are standard agent YAMLs in `config/agents/council/`. Each has its own persona, constraints, and `defer_to: []` (members do not defer during deliberation):

```yaml
# config/agents/council/architect.yaml
agent_id: architect
name: Architect
persona: |
  You are a software architect. Your role is to evaluate decisions
  from a system design and technical coherence perspective...
defer_to: []
constraints:
  max_tokens: 2048
  max_iterations: 8
```

## Usage

### Via CLI Command

```
/council dev-squad on "evaluate the architecture risk of switching from Postgres to DynamoDB"
```

### Via Workflow (Agent-Invoked)

A supervisor agent can invoke a council deliberation as part of a workflow. The council result (decision, confidence, member analyses) is available to subsequent workflow steps.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Supervisor                      │
│  ┌──────────────┐   ┌────────────────────────┐  │
│  │    Router     │   │  CouncilOrchestrator   │  │
│  │  /council →   │──▶│  deliberate()          │  │
│  │  DEST_COUNCIL │   │                        │  │
│  └──────────────┘   │  _defer_to_member() ────│──▶ Supervisor.defer_to_agent()
│                     │                        │  │
│                     │  _parse_decision()     │  │
│                     └────────────────────────┘  │
└─────────────────────────────────────────────────┘
         │                           │
         ▼                           ▼
  CouncilRegistry            CouncilSession
  (in-memory YAML cache)     (per-deliberation audit trail)
```

Key components:

- **`CouncilRegistry`** — loaded from `config/councils/*.yaml` at startup. Maps `council_id → CouncilDefinition`.
- **`CouncilOrchestrator`** — runs the four-phase deliberation via `supervisor.defer_to_agent()`.
- **`CouncilSession`** — per-deliberation state capturing all analyses, counter-analyses, and the final outcome.
- **`Agent prompts`** — phase-specific prompt builders in `src/agent/council/prompts.py`.

## Future Directions

- **Parallel member execution** — members currently run sequentially; parallel execution would reduce latency.
- **Iterative deliberation** — allow multiple rounds of analysis/counter-analysis before arbitration.
- **Dynamic councils** — compose councils at runtime from available agents rather than pre-defining them.
- **Consensus scoring** — `require_consensus` field is defined but not yet enforced.
- **Scored confidence** — confidence currently maps HIGH→0.9, MEDIUM→0.6, LOW→0.3; a richer model could incorporate member agreement metrics.
