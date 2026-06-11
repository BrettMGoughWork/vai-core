`vai-core` is a clean, deterministic agent runtime built for clarity and long-term maintainability.

*Note: this project is currently in early development*

It’s built around a small set of stable concepts — models, capabilities, skills, and a safety substrate — that keep the system predictable even as you extend it.

The core idea is simple: give LLMs structured jobs, not free rein. The runtime forces clean JSON output, mediates all external calls through a strict capability system, and bakes in safety, observability, and self-healing by default.

---

## 🚀 Primary Interface (REPL)

**Right now, the project is driven through a single interactive REPL.** As the system matures toward channels, ingress, transport, and control planes, this REPL will remain the development cockpit — a direct line into the S2 planner, skill execution, and breakage repair loop.

### Start the REPL

```
# Real LLM (default — set LLM_PROVIDER + LLM_MODEL env vars)
python -m tools.testing_harness.repl_harness

# Mock LLM (deterministic, no API calls)
python -m tools.testing_harness.repl_harness --mock
```

### What it does

Each turn at the `s2>` prompt runs the full pipeline: **plan → breakage detection → repair → execute skills**. The plan, breakage report, repair outcome, and skill execution results are all displayed inline. Conversation context is remembered across turns — prior prompts and assistant outputs feed back to the LLM on each request.

Type `:help` inside the REPL to see all commands.

---

### Dependencies

**LLM**: Set `DEEPSEEK_API_KEY` (or configure another provider in `config/config.yaml`).

**Embeddings** (for skill discovery fallback — used only when the LLM fails to pick a skill):

| Mode | Config `provider:` | Requirements |
|------|--------------------|-------------|
| Local (default) | `local` | `pip install sentence-transformers` — runs MiniLM-L6-v2 in-process, models cached in `.models/` |
| Cloud API | `openai` | Set `OPENAI_API_KEY` env var, uses text-embedding-3-small |
| Mock (tests) | `mock` | No dependencies, returns deterministic zero-vectors |

**Search**: See `search:` block in `config/config.yaml`. Tavily requires `TAVILY_API_KEY`, DuckDuckGo is keyless.

Core Concepts
   
*Models* — pure data shapes. Everything the system moves around is strongly typed.  
*Capabilities* — declare what the agent can do (read files, make requests, etc), without giving it direct access.  
*Skills* — small, focused behaviours that combine prompts, guardrails, and logic on top of capabilities.  
*Safety Substrate* — the runtime’s guardrails. It controls execution, handles panics, manages degraded modes, and keeps things stable.  

### Extending with CLI & MCP Primitives

The capability system supports three kinds of primitives (Python, CLI, MCP).
Python primitives are auto-discovered; CLI and MCP primitives are loaded from
config via the external loaders.

**Register CLI primitives** — pass a ``cli_config`` dict to ``load_all_primitives``:

```python
from src.capabilities.primitives.stdlib import load_all_primitives
from src.capabilities.registry.primitive_registry import PrimitiveRegistry

registry = PrimitiveRegistry()
count = load_all_primitives(registry, cli_config={
    "my-tool": {"command": "my-tool", "description": "Does something useful"},
})
```

**Register MCP primitives** — pass an ``mcp_config`` dict:

```python
count = load_all_primitives(registry, mcp_config={
    "my-server": {
        "command": "npx",
        "args": ["@myserver/mcp-server"],
        "env": {"API_KEY": "..."},
    },
})
```

Each entry creates a ``CLIPrimitive`` or ``MCPPrimitive`` instance and registers
it by name in the ``PrimitiveRegistry`` alongside the auto-discovered stdlib
primitives. Skills can then reference these primitives by name the same way
they reference any Python primitive.

### Agent-Authored Skills & Quarantine

When an LLM agent authors a new skill at runtime, the skill passes through a multi-layer safety pipeline before it can be used:

1. **Structural Safety** — recursive self-references, unbounded loops, and dynamic primitive selection are rejected.
2. **Semantic Safety** — misleading descriptions, high-risk primitive chains, and embedded code blocks are audited.
3. **Behavioural Sandbox** — the skill executes in a thread‑isolated sandbox with mock primitives. Only safe behaviour passes.
4. **Quarantine** — skills that pass layers 1-3 are placed in **quarantine**, not the active registry. Quarantined skills are invisible to discovery (`get`, `find`, `find_semantic`, `ordered_list`).

**⚠️ Human governance step required.** A quarantined skill will **never** execute until a human (or automated governance agent) explicitly approves it via `python -m tools.quarantine_cli approve`. There is currently no cross‑channel notification to alert a human that a skill is waiting for review — this is deferred to Stratum 4. Until then, operators must poll `python -m tools.quarantine_cli list` or check the quarantine manually.

Repository Layout

src/strategy/ — planning, types, contracts, runtime orchestration  
src/capabilities/primitives/ — reusable building blocks (Python, CLI, MCP)  
src/capabilities/skills/ — reusable agent behaviours  
src/capabilities/registry/ — primitive & skill registries, loaders, safety validators, quarantine  
src/runtime/ — agent-host communication, TUI, memory substrate  
src/strategy/planning/adapters/ — S2→S3 boundary adapter  
docs/architecture/ — deep technical docs



## Developer Tools


### Inspector Dashboard

The Stratum-2 Inspection Dashboard is a read-only, developer-facing TUI for visualizing agent cycle traces and memory substrate state in real time. It provides a safe, side-effect-free way to inspect agent activity and health.

Usage:
    python -m tools.inspector.dashboard

Optional arguments allow you to specify a trace directory or enable live watching.


### Fetch Test Harness (`tools/fetch_harness/`)

A scenario-driven test harness for the HTTP fetch subsystem. Define websites by
hardness level (simple, hardened, javascript, spa, antibot) and the harness
reports success metrics for each.

Usage:
    # List available scenarios
    python -m tools.fetch_harness.harness --list

    # Run all scenarios
    python -m tools.fetch_harness.harness

    # Filter by hardness level
    python -m tools.fetch_harness.harness --hardness simple

    # Run one scenario with JSON output
    python -m tools.fetch_harness.harness --name httpbin_get --json

    # Quick-add a new scenario
    python -m tools.fetch_harness.harness --add "mysite,https://example.com,simple"

Output includes per-scenario metrics (status, timing, body length, cookies) and
detailed check-level pass/fail assessment against expected characteristics.

### Manual Cycle Runner (`run_cycle.py`)

A single-cycle debug REPL for the S2 ↔ S1 ↔ LLM boundary. Runs exactly one cycle, prints full trace, and exits. Useful for debugging prompt construction, schema validation, and state transitions.

Usage:
    python tools/testing_harness/run_cycle.py "your request" --backend simulation
    python tools/testing_harness/run_cycle.py "your request" --backend real_llm --verbose

Options:
    --backend        "simulation" (deterministic mock) or "real_llm" (DeepSeek)
    --verbose, -v    Print full details (PromptRequest, PromptResponse, S2 updates)
    --silent         Suppress trace printing
    --example, -e    Use built-in example request

### E2E Harness (`tools/testing_harness/e2e_harness.py`)

End-to-end Prompt → LLM → Planner → Skill pipeline. Sends a prompt through the real LLM, discovers skills via S3Adapter, generates a plan via SubgoalPlanner, and executes referenced skills through the S3 SkillRunner.

Usage:
    # Run with default real LLM backend
    python -m tools.testing_harness.e2e_harness "echo back: hello world"

    # Run with mock LLM (deterministic, no API calls)
    python -m tools.testing_harness.e2e_harness "echo test" --backend mock

    # JSON output for scripting
    python -m tools.testing_harness.e2e_harness "list files" --json

Options:
    prompt            (positional) The user prompt to send through the pipeline
    --backend         "real_llm" (default) or "mock" (deterministic MockLLM)
    --json            Output machine-readable JSON instead of formatted text

Each turn runs: create subgoal → plan generation → breakage detection → repair (if not clean) → execute skills. The full plan, breakage report, repair outcome, and skill execution results are displayed after each turn.


### Statistical Conformance Runner (`tests/statistical/`)

A reusable, scenario-agnostic harness for probabilistic testing against the agent runtime. Runs a scenario N times, extracts metrics, aggregates results, and evaluates against configurable thresholds.

Usage:
    # Run a scenario with default repetitions from the scenario file
    python -m tests.statistical.cli --scenario tiny_plan1

    # Override repetitions
    python -m tests.statistical.cli --scenario tiny_plan1 --repetitions 100

    # With real LLM backend
    python -m tests.statistical.cli --scenario tiny_plan1 --repetitions 10 --backend real_llm --verbose

    # List available scenarios
    python -m tests.statistical.cli --list

    # Skip threshold evaluation (report only)
    python -m tests.statistical.cli --scenario tiny_plan1 --repetitions 50 --no-thresholds

Metrics collected per run:
    • JSON validity — is the S1 response valid JSON?
    • Schema validity — does it conform to the PromptResponse schema?
    • Drift signals — count of behavioural drift signals detected
    • Repair attempts — count of repair operations triggered
    • Catastrophic failures — runs that crashed or produced no usable output
    • Invariant violations — S2 invariants that did not hold
    • Trace stability — measure of deterministic output reproducibility

Scenarios are defined as JSON files in `tests/statistical/scenarios/` and include:
    • `tiny_plan1` — 1 subgoal, 1 segment (baseline)
    • `tiny_plan3` — 1 subgoal, 3 segments (multi-segment)
    • `tiny_plan2x2` — 2 subgoals, 2 segments each (multi-subgoal)

Add new scenarios by creating a JSON file in that directory with the same shape.