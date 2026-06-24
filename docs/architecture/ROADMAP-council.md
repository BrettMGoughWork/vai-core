# Council Arbitration — Implementation Roadmap

> **Status**: Plan — ready for implementation
> **Sprint**: Council C1 (new sprint, depends on D1 agent-deferral completion)
> **Target**: First-class multi-agent deliberation and arbitration pattern
>
> **Design principle**: Compose entirely from existing building blocks
>   (`defer_to_agent`, `AgentState`, `ContextBridge`, `WorkflowDefinition`,
>   `PatternDefinition`, `AgentRegistry`).  Add a thin orchestration layer
>   for fan-out/fan-in; do NOT re-invent agent lifecycle, LLM invocation, or
>   state management.

---

## 1.  What It Is

Council Arbitration is a **five-phase deliberation pattern** where multiple
agents analyse the same problem from different perspectives, challenge each
other's reasoning, and an impartial arbitrator synthesises a final decision.

```
                          ┌──────────────────┐
                          │  1. Convene      │
                          │  Problem is put  │
                          │  to the council  │
                          └────────┬─────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                        ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  2. Analysis    │   │  2. Analysis    │   │  2. Analysis    │
│  Member A       │   │  Member B       │   │  Member C       │
│  (perspective 1)│   │  (perspective 2)│   │  (perspective 3)│
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               │  (analyses shared)
                               ▼
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                        ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│  3. Counter     │   │  3. Counter     │   │  3. Counter     │
│  Member A ← B,C │   │  Member B ← A,C │   │  Member C ← A,B│
└────────┬────────┘   └────────┬────────┘   └────────┬────────┘
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               │  (all analyses + counters forwarded)
                               ▼
                    ┌─────────────────────┐
                    │  4. Arbitrate       │
                    │  Neutral arbitrator │
                    │  weighs all input   │
                    │  → final decision   │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  5. Hand-back       │
                    │  Decision returned  │
                    │  to calling context │
                    └─────────────────────┘
```

### When to use

- Ambiguity exists and direction is required
- An important architectural or product decision needs multiple perspectives
- Risk assessment with competing priorities (speed vs quality vs cost)
- The "dev squad" needs to reach consensus on a technical approach

### When NOT to use

- Straightforward, non-controversial decisions (just use a single agent)
- Latency-critical paths (council involves N+1 agent turns — sequential in V1)
- Decisions where the cost of multiple LLM calls outweighs the benefit

---

## 2.  Design Decisions

### 2.1  Council is built on `defer_to_agent`, not a new lifecycle

The existing `Supervisor.defer_to_agent()` already handles:
- Suspending the delegator agent
- Creating, activating, and running a delegate agent to completion
- Injecting the delegate's response into the delegator's `supervisor_metadata`
- Resuming the delegator

A council is **multiple sequential deferrals** orchestrated by a thin
`CouncilOrchestrator`.  Each council member is a delegate; the orchestrator
is the delegator.  Phase 2 (counter-analysis) shares the outputs of Phase 1
via the `ContextBridge` pattern.

**What we do NOT do**: We do not create a new `LifecycleState` for council
members.  They follow the standard CREATED → ACTIVATED → RUNNING →
COMPLETED/FAILED lifecycle.  The orchestrator simply calls `defer_to_agent()`
N times.

### 2.2  V1 is sequential; V2 adds fan-out parallelism

Each council member runs **sequentially** in V1.  This is simpler, easier to
debug, and uses only existing `defer_to_agent` machinery.  The S4 roadmap
already calls out parallel sub-agents (items 11.9/11.10) — council V2 will
upgrade to fan-out/fan-in when those primitives land.

### 2.3  Council composition is config-driven; both general and dev-squad are provided

The user is unsure whether council composition should be general (strategist,
critic, risk-assessor) or specific (architect, PM, engineer, QA, delivery
lead).  **We ship both** as pre-built council definitions in YAML.  Users
can also define custom councils.  Council composition is decoupled from the
orchestration logic — the orchestrator doesn't care *who* the members are.

| Council | Members | Arbitrator | Use-case |
|---|---|---|---|
| `general-nominal` | Strategist, Critic, Risk-Assessor | balanced-adjudicator | Universal decision-making |
| `dev-squad` | Architect, Product Manager, Engineer, Quality Analyst, Delivery Lead | tech-lead-adjudicator | Software design/architecture decisions |
| `security-review` (future) | Threat Modeller, Defender, Attacker | security-architect | Security-sensitive decisions |

### 2.4  Pattern + Orchestrator, not just Pattern

A **pure pattern** (LLM instructions only) would not be reliable enough —
the LLM might skip phases, hallucinate council member outputs, or fail to
properly isolate perspectives.  The **orchestrator** enforces the phases
deterministically while the **pattern** provides LLM-level guidance for how
each phase should be conducted.

---

## 3.  Data Model

### 3.1  `CouncilDefinition` (new domain type)

```python
# src/domain/council.py

@dataclass(frozen=True)
class CouncilDefinition:
    council_id: str                              # e.g. "general-nominal"
    name: str                                    # Human-readable
    description: str                             # When to use this council
    arbitrator_agent_id: str                     # The neutral decision-maker
    member_agent_ids: tuple[str, ...]            # Council members (ordered)
    max_analysis_tokens: int = 2000              # Truncation limit per member
    max_counter_tokens: int = 1500               # Truncation limit for counter
    require_consensus: bool = False              # If True, iterate until consensus (future)
```

### 3.2  `CouncilSession` (runtime state)

```python
# src/agent/council/session.py

@dataclass
class CouncilSession:
    session_id: str
    council_def: CouncilDefinition
    problem_statement: str
    phase: str                                   # "convene" | "analysis" | "counter" | "arbitration" | "complete"
    analyses: dict[str, str]                     # member_agent_id → analysis text
    counters: dict[str, str]                     # member_agent_id → counter text
    decision: str | None
    started_at: datetime
    completed_at: datetime | None
```

### 3.3  `CouncilOutcome` (returned to caller)

```python
@dataclass
class CouncilOutcome:
    council_id: str
    decision: str                                # Arbitrator's final decision
    member_analyses: dict[str, str]              # For audit trail
    member_counters: dict[str, str]
    confidence: float                            # 0.0 – 1.0 (arbitrator's self-assessment)
    dissent_notes: str | None                    # Any minority opinions flagged
```

---

## 4.  Implementation Plan

### 4.1  File structure (new files only)

```
vai-core/
├── src/
│   ├── domain/
│   │   └── council.py                  ★ CouncilDefinition, CouncilOutcome
│   ├── agent/
│   │   └── council/
│   │       ├── __init__.py
│   │       ├── orchestrator.py         ★ CouncilOrchestrator
│   │       ├── session.py              ★ CouncilSession state tracker
│   │       ├── prompts.py              ★ Phase-specific prompt builders
│   │       └── loader.py               ★ load_councils_from_directory()
│   └── agent/workflow/
│       └── workflow_definition.py       ★ Add council_deliberate StepType
├── config/
│   ├── councils/
│   │   ├── general-nominal.yaml        ★ Strategist + Critic + Risk-Assessor
│   │   └── dev-squad.yaml              ★ Architect + PM + Engineer + QA + Delivery Lead
│   ├── patterns/
│   │   └── council-arbitration.yaml    ★ LLM-readable pattern instructions
│   └── agents/
│       └── council/                    ★ Council member agent definitions
│           ├── strategist.yaml
│           ├── critic.yaml
│           ├── risk-assessor.yaml
│           ├── balanced-adjudicator.yaml
│           ├── architect.yaml
│           ├── product-manager.yaml
│           ├── sofware-engineer.yaml
│           ├── quality-analyst.yaml
│           ├── delivery-lead.yaml
│           └── tech-lead-adjudicator.yaml
└── tests/
    └── agent/
        └── council/
            ├── test_orchestrator.py
            ├── test_session.py
            ├── test_loader.py
            └── fixtures/
                └── minimal-council.yaml
```

### 4.2  Implementation phases

#### Phase C1.1 — Domain model & config (2–3 tasks)

| Task ID | Description | Files |
|---|---|---|
| `council-domain` | Create `CouncilDefinition` and `CouncilOutcome` dataclasses in `src/domain/council.py` | 1 new file |
| `council-loader` | Create YAML loader: `load_council_definition(path)` and `load_councils_from_directory(dir)` | `src/agent/council/loader.py` |
| `council-configs` | Create `general-nominal.yaml` and `dev-squad.yaml` council definitions | 2 new YAML files |

**`CouncilDefinition` YAML schema** (what `general-nominal.yaml` looks like):

```yaml
# config/councils/general-nominal.yaml
council_id: general-nominal
name: "General Nominal Council"
description: >
  Universal council for ambiguous decisions.  Three distinct perspectives
  (strategic, critical, risk-aware) plus a balanced adjudicator.
arbitrator_agent_id: balanced-adjudicator
member_agent_ids:
  - strategist
  - critic
  - risk-assessor
max_analysis_tokens: 2000
max_counter_tokens: 1500
require_consensus: false
```

**`dev-squad.yaml`**:

```yaml
# config/councils/dev-squad.yaml
council_id: dev-squad
name: "Dev Squad Council"
description: >
  Software design & architecture decisions.  Five perspectives mirror a
  cross-functional product team: Architect, Product Manager, Engineer,
  Quality Analyst, Delivery Lead.  Adjudicated by the Tech Lead.
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

---

#### Phase C1.2 — Agent definitions (1 task)

| Task ID | Description | Files |
|---|---|---|
| `council-agents` | Create all 9 council agent YAML definitions with distinct personas, defer_to lists, and patterns | 9 new YAML files |

Each council member agent needs:
- A **persona** that defines their perspective and biases
- A `defer_to` list that **excludes other council members** (members don't defer to each other; the orchestrator delegates to them)
- The `council-arbitration` pattern in their `patterns` list

**Example — `strategist.yaml`**:

```yaml
# config/agents/council/strategist.yaml
agent_id: strategist
identity:
  name: "Strategist"
  description: "Long-range strategic thinker focused on goals, trade-offs, and competitive landscape"

persona:
  system_prompt: |
    You are a strategic advisor.  Your perspective is:
    - Focus on long-term outcomes, not short-term convenience
    - Identify strategic trade-offs: what do we gain vs what do we sacrifice?
    - Consider second-order effects: what happens after this decision plays out?
    - Align recommendations with overarching goals and mission
    - Think in terms of opportunity cost

    When participating in a council:
    - Be concise and structured.  Use "Analysis:" and "Recommendation:" sections.
    - Acknowledge uncertainty where it exists.
    - Flag assumptions explicitly.
  temperature: 0.4

tools: []
workflows: []
patterns:
  - council-arbitration
defer_to:
  - balanced-adjudicator  # Only the arbitrator, not other council members
```

**Example — `balanced-adjudicator.yaml`** (the arbitrator for general-nominal):

```yaml
# config/agents/council/balanced-adjudicator.yaml
agent_id: balanced-adjudicator
identity:
  name: "Balanced Adjudicator"
  description: "Impartial decision-maker who weighs multiple perspectives and selects the best course of action based on merit"

persona:
  system_prompt: |
    You are a neutral, balanced adjudicator.  Your role is NOT to advocate for any
    position, but to evaluate competing analyses and determine the best path forward.

    Your principles:
    - Stay impartial — do not favour any council member's perspective
    - Weigh arguments based on evidence, logic, and alignment with goals
    - Acknowledge trade-offs; explain WHY one path is chosen over others
    - If no clear winner emerges, say so and recommend gathering more information
    - Structure your decision as: "Decision:", "Rationale:", "Trade-offs Accepted:",
      "Risks/Unknowns:", "Confidence: [0.0-1.0]"

    You do not participate in the analysis phase — you only adjudicate after all
    analyses and counter-analyses are complete.
  temperature: 0.2  # Lower temperature for consistent, balanced decisions

tools: []
workflows: []
patterns:
  - council-arbitration
defer_to: []  # Arbitrator never defers — it is the terminal decision-maker
```

The remaining 7 agents follow the same structure with persona-appropriate `system_prompt` and `description` fields.  See **Appendix A** for all persona descriptions.

---

#### Phase C1.3 — Council orchestrator (3–4 tasks)  ★ CORE

| Task ID | Description | Files |
|---|---|---|
| `council-session` | Create `CouncilSession` state tracker in `src/agent/council/session.py` | 1 new file |
| `council-prompts` | Create phase-specific prompt builders in `src/agent/council/prompts.py` | 1 new file |
| `council-orch` | Create `CouncilOrchestrator` in `src/agent/council/orchestrator.py` — the main class | 1 new file |

**`CouncilOrchestrator` design** (`src/agent/council/orchestrator.py`):

The orchestrator receives a `Supervisor` instance (DI-injected) and uses
`supervisor.defer_to_agent()` for every council member interaction.

```python
class CouncilOrchestrator:
    """Orchestrates a multi-agent council deliberation.

    Built entirely on Supervisor.defer_to_agent().  Each council member is
    invoked as a delegate; the orchestrator manages the multi-phase lifecycle
    (convene → analysis → counter → arbitration → handback).
    """

    def __init__(self, supervisor: Supervisor):
        self._supervisor = supervisor

    async def deliberate(
        self,
        council_def: CouncilDefinition,
        problem: str,
        calling_agent_state: AgentState,
    ) -> CouncilOutcome:
        """Run a full council deliberation.

        Parameters
        ----------
        council_def:
            The council configuration (members + arbitrator).
        problem:
            The problem statement put to the council.
        calling_agent_state:
            The agent that invoked the council (used for deferral context).

        Returns
        -------
        CouncilOutcome:
            The final decision with audit trail.
        """
        session = CouncilSession.create(council_def, problem)

        # ── Phase 1: Convene ──────────────────────────────────
        # (already handled by session creation)

        # ── Phase 2: Individual Analysis ──────────────────────
        for member_id in council_def.member_agent_ids:
            analysis = await self._defer_to_member(
                calling_agent_state,
                member_id,
                prompt=self._prompts.build_analysis_prompt(problem, member_id),
            )
            session.analyses[member_id] = analysis

        # ── Phase 3: Counter-Analysis ─────────────────────────
        # Each member sees all OTHER members' analyses (not their own)
        for member_id in council_def.member_agent_ids:
            others = {
                mid: analysis
                for mid, analysis in session.analyses.items()
                if mid != member_id
            }
            counter = await self._defer_to_member(
                calling_agent_state,
                member_id,
                prompt=self._prompts.build_counter_prompt(problem, member_id, others),
            )
            session.counters[member_id] = counter

        # ── Phase 4: Arbitration ──────────────────────────────
        decision = await self._defer_to_member(
            calling_agent_state,
            council_def.arbitrator_agent_id,
            prompt=self._prompts.build_arbitration_prompt(
                problem, session.analyses, session.counters
            ),
        )

        # ── Phase 5: Hand-back ────────────────────────────────
        outcome = self._parse_decision(decision, session)
        session.complete(outcome)
        return outcome
```

**How `_defer_to_member()` works**:

```python
async def _defer_to_member(
    self,
    calling_state: AgentState,
    target_agent_id: str,
    prompt: str,
) -> str:
    """Defer to a council member and extract their response.

    Uses Supervisor.defer_to_agent() — suspend → create delegate →
    activate → run to completion → inject result → resume.
    """
    # The calling_state is temporarily mutated by defer_to_agent
    # (it suspends, creates delegate, runs it, resumes).
    # We extract the deferral_result from supervisor_metadata.
    result_state = self._supervisor.defer_to_agent(
        state=calling_state,
        delegate_agent_id=target_agent_id,
        deferral_prompt=prompt,
    )
    deferral_result = result_state.supervisor_metadata.get("deferral_result", {})
    return deferral_result.get("response", "")
```

**Key design points**:

1. **No new lifecycle states** — council members go through the standard CREATED→ACTIVATED→RUNNING→COMPLETED flow managed by `defer_to_agent()`.
2. **Context isolation** — each member gets only the problem statement + relevant phase context (analyses from other members).  They do NOT see the full conversation history of the calling agent (prevents bias).
3. **Truncation** — member outputs are truncated at `max_analysis_tokens` (2000) and `max_counter_tokens` (1500) to prevent context blow-up when all are gathered for the arbitrator.
4. **Error handling** — if a member fails (lifecycle → FAILED), their analysis/counter is recorded as `"[Member X failed to respond]"` and the council continues.  The arbitrator is informed of the failure.
5. **Timeout** — each `defer_to_agent` call respects the Supervisor's existing timeout configuration.

---

#### Phase C1.4 — Pattern & workflow integration (2 tasks)

| Task ID | Description | Files |
|---|---|---|
| `council-pattern` | Create `council-arbitration` pattern YAML with LLM-readable instructions | `config/patterns/council-arbitration.yaml` |
| `council-step-type` | Add `council_deliberate` to `StepType` enum in `workflow_definition.py` | 1 edit |

**Pattern** (`config/patterns/council-arbitration.yaml`):

```yaml
# config/patterns/council-arbitration.yaml
pattern_id: council-arbitration
name: "Council Arbitration"
description: >
  Multi-agent deliberation and arbitration pattern.  Use when an important
  decision requires multiple perspectives and impartial adjudication.
version: "1.0.0"

primitives: []

instructions: |
  # Council Arbitration Pattern

  You are participating in a council deliberation.  The council has multiple
  members with different perspectives, plus a neutral arbitrator who makes the
  final decision.

  ## Your Role

  If you are a COUNCIL MEMBER:
  - You are NOT the decision-maker.  Your job is to provide your best analysis
    from your specific perspective.
  - Be concise and structured.  Use clear sections: Analysis, Recommendation,
    Assumptions, Risks.
  - When providing counter-analysis: address the OTHER members' points directly.
    Point out flaws, overlooked considerations, or strengths you agree with.
    Do NOT simply repeat your original analysis.
  - Stay in character — your perspective should colour your analysis.

  If you are the ARBITRATOR:
  - You do NOT participate in the analysis or counter-analysis phases.
  - You receive ALL analyses and counter-analyses.
  - Weigh arguments based on evidence, logic, and alignment with stated goals.
  - Output MUST include: "Decision:", "Rationale:", "Trade-offs Accepted:",
    "Risks/Unknowns:", "Confidence: [0.0-1.0]"
  - If equally valid paths exist, pick one and explain why the tie was broken.
  - If critical information is missing, flag it rather than guessing.

  ## Phases

  1. Analysis — each member gives their independent analysis
  2. Counter-Analysis — each member critiques the others' analyses
  3. Arbitration — the arbitrator synthesises and decides
  4. Hand-back — the decision is returned with audit trail
```

**Workflow step type** (edit `src/agent/workflow/workflow_definition.py`):

Add `COUNCIL_DELIBERATE = "council_deliberate"` to the `StepType` enum.  When
the workflow engine encounters this step type, it emits a `StepOutcome` with
`action="council_deliberate"`.  The `WorkflowInvoker` (or Supervisor) then
routes to the `CouncilOrchestrator`.

The workflow YAML step looks like:

```yaml
steps:
  - id: design_decision
    type: council_deliberate
    config:
      council_id: dev-squad
      problem: "{{ workflow_state.problem_statement }}"
    transitions:
      on_success: implement_decision
      on_failure: escalate_to_human
```

---

#### Phase C1.5 — DI wiring & gateway integration (1 task)

| Task ID | Description | Files |
|---|---|---|
| `council-wiring` | Wire `CouncilOrchestrator` into `composition_root.py`; add council YAML loading | `src/agent/composition_root.py` |

Changes to `composition_root.py`:

```python
# After workflow/pattern loading (~line 80):
_council_defs = load_councils_from_directory(COUNCILS_DIR)
_council_orchestrator = CouncilOrchestrator(supervisor=_supervisor)
```

The `CouncilOrchestrator` becomes available anywhere the Supervisor is available — it's a thin wrapper around `defer_to_agent()`.

---

#### Phase C1.6 — Tests (2 tasks)

| Task ID | Description | Files |
|---|---|---|
| `council-unit-tests` | Unit tests for `CouncilDefinition` loading, `CouncilSession` state transitions, prompt builders | `tests/agent/council/` |
| `council-integration` | Integration test: run a minimal 2-member council end-to-end with mock LLM | `tests/agent/council/test_orchestrator.py` |

**Test scenarios**:

1. `test_load_general_nominal_council` — YAML parses correctly into `CouncilDefinition`
2. `test_load_dev_squad_council` — 5-member council loads with correct arbitrator
3. `test_session_phases` — `CouncilSession` transitions through all phases correctly
4. `test_analysis_prompt_includes_problem` — prompt builder output contains the problem statement
5. `test_counter_prompt_excludes_own_analysis` — member does NOT see their own analysis in counter phase
6. `test_member_failure_graceful` — if one member fails, council continues and arbitrator is informed
7. `test_full_council_simulation` — end-to-end with a mocked `Supervisor` returning canned responses
8. `test_arbitrator_decision_parsed` — `CouncilOutcome` correctly parses arbitrator's structured output

---

## 5.  Key Design Concerns & Mitigations

### 5.1  Context blow-up

**Problem**: 5 members × 2000 tokens analysis + 5 members × 1500 tokens counter
= 17,500 tokens just for council output, plus the problem statement and prompt
overhead.  The arbitrator (and later phases) may exceed context limits.

**Mitigation**:
- Truncation at `max_analysis_tokens` / `max_counter_tokens` (configurable per council)
- Summarisation mode (future V2): a "council secretary" agent summarises all
  analyses before passing to the arbitrator
- The orchestrator logs full untruncated output for audit, even if truncated
  for the arbitrator

### 5.2  Arbitration neutrality

**Problem**: The arbitrator is just another LLM agent.  It may favour certain
perspectives or hallucinate consensus.

**Mitigation**:
- Arbitrator persona explicitly instructs neutrality (see `balanced-adjudicator.yaml`)
- Low temperature (0.2) for consistent, balanced outputs
- Structured output format (`Decision:`, `Rationale:`, `Confidence:`)
- In V2: confidence below threshold triggers re-deliberation or human escalation

### 5.3  Timeout & error handling

**Problem**: A council member may hang, error, or return garbage.

**Mitigation**:
- Each `defer_to_agent()` call respects existing Supervisor timeout
- Member failure → recorded as `"[Member X failed to respond]"` → council continues
- If ALL members fail → council fails with `CouncilError`
- If arbitrator fails → council fails (no decision possible)
- The `CouncilOutcome` carries a `dissent_notes` field for the arbitrator to flag
  any member whose input was unusable

### 5.4  Council composition — general vs specific

**Problem**: The user is unsure whether councils should be generic (any use-case)
or domain-specific (dev squad).

**Resolution**: We ship both as pre-built YAML configs.  Council composition is
**data, not code**.  Users can:
- Use `general-nominal` for any ambiguous decision
- Use `dev-squad` for software design decisions
- Create custom councils by writing a YAML file and registering agents

The orchestrator is agnostic to member personas — it only requires valid agent
IDs that exist in the `AgentRegistry`.

### 5.5  Recursive deferral safety

The existing `DepthGuard` (max depth 3) and acyclicity validator apply to all
`defer_to_agent` calls, including those made by the `CouncilOrchestrator`.
The arbitrator's `defer_to: []` ensures it cannot create an infinite loop.

---

## 6.  Future Enhancements (V2, beyond this plan)

| Enhancement | Description | Sprint |
|---|---|---|
| **Parallel fan-out** | Run all Phase 2 analyses concurrently via S4 sub-agents (items 11.9/11.10) | After S4 parallelism lands |
| **Consensus mode** | `require_consensus: true` — iterate analysis/counter cycles until arbitrator detects convergence or max rounds reached | Council V2 |
| **Council secretary** | Summarisation agent that compresses member output before arbitration to prevent context blow-up | Council V2 |
| **Confidence-based escalation** | If arbitrator confidence < 0.4, escalate to human or re-run with different council | Council V2 |
| **Post-hoc audit** | Log full council transcripts to S4 for later analysis and pattern improvement | Council V2 |
| **Dynamic member selection** | AgentSelectionStrategy picks council members based on problem domain (e.g., "security" → security-review council) | Council V3 |

---

## 7.  Sprint Task Summary

| Phase | Task ID | Description | Est. effort |
|---|---|---|---|
| C1.1 | `council-domain` | `CouncilDefinition` + `CouncilOutcome` dataclasses | Small |
| C1.1 | `council-loader` | YAML loader for council definitions | Small |
| C1.1 | `council-configs` | `general-nominal.yaml` + `dev-squad.yaml` | Small |
| C1.2 | `council-agents` | 9 council agent YAMLs with personas | Medium |
| C1.3 | `council-session` | `CouncilSession` state tracker | Small |
| C1.3 | `council-prompts` | Phase-specific prompt builders | Medium |
| C1.3 | `council-orch` | `CouncilOrchestrator` (the main class) | Large |
| C1.4 | `council-pattern` | `council-arbitration` pattern YAML | Small |
| C1.4 | `council-step-type` | `council_deliberate` workflow step type | Small |
| C1.5 | `council-wiring` | DI wiring in `composition_root.py` | Small |
| C1.6 | `council-unit-tests` | Unit tests for all new modules | Medium |
| C1.6 | `council-integration` | End-to-end integration test | Medium |

---

## Appendix A — Council Agent Personas

### General Nominal Council

| Agent ID | Persona summary |
|---|---|
| `strategist` | Long-range strategic thinker. Focuses on goals, trade-offs, opportunity cost, second-order effects. Optimistic about execution capability. |
| `critic` | Devil's advocate. Identifies flaws, hidden assumptions, and failure modes. Pessimistic by design — stress-tests ideas. |
| `risk-assessor` | Probability-aware risk analyst. Evaluates likelihood × impact of risks. Distinguishes between acceptable and unacceptable risk. |
| `balanced-adjudicator` | Neutral arbitrator. Weighs all perspectives impartially. Outputs structured decisions with rationale and confidence. |

### Dev Squad Council

| Agent ID | Persona summary |
|---|---|
| `architect` | System design and technical coherence. Focuses on scalability, maintainability, modularity, tech debt. Thinks in terms of components and contracts. |
| `product-manager` | User value and business alignment. Focuses on user needs, market fit, prioritisation, scope trade-offs. Thinks in terms of outcomes over output. |
| `software-engineer` | Implementation pragmatism. Focuses on feasibility, code quality, developer experience, technical constraints. Thinks in terms of what can actually be built. |
| `quality-analyst` | Quality and reliability. Focuses on edge cases, testability, regression risk, non-functional requirements. Thinks in terms of "what could go wrong?" |
| `delivery-lead` | Delivery and iteration. Focuses on timelines, dependencies, incremental value, risk mitigation through sequencing. Thinks in terms of "how do we ship this safely?" |
| `tech-lead-adjudicator` | Technical leadership with balanced judgment. Synthesises cross-functional input into actionable technical decisions. Outputs decision + implementation guidance. |

---

## Appendix B — Key Files to Reference During Implementation

| File | What to look at |
|---|---|
| `src/agent/supervisor.py:968` (`defer_to_agent`) | The core primitive the orchestrator calls. Understand the full lifecycle: suspend → create → activate → run → extract result → resume. |
| `src/agent/deferral/context_bridge.py` | How delegate prompts are built and responses injected. The council prompt builders follow this pattern. |
| `src/agent/composition_root.py` | Where to wire the `CouncilOrchestrator`. Follow the pattern used for `TodoOrchestrator` and `WorkflowEngine`. |
| `src/agent/workflow/workflow_definition.py` | Where to add `COUNCIL_DELIBERATE` to `StepType`. |
| `src/domain/patterns.py` | `PatternDefinition` structure — used as reference for the `council-arbitration` pattern. |
| `docs/architecture/agent-deferral.md` | Full deferral design doc. Council builds directly on this. |
| `config/agents/*.yaml` | Existing agent YAML format. Council member agents follow the same schema. |
| `tests/agent/test_deferral_integration.py` | Integration test patterns for deferral — council integration tests follow the same approach. |
