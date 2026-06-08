`vai-core` is a clean, deterministic agent runtime built for clarity and long-term maintainability.

It’s built around a small set of stable concepts — models, capabilities, skills, and a safety substrate — that keep the system predictable even as you extend it.

The core idea is simple: give LLMs structured jobs, not free rein. The runtime forces clean JSON output, mediates all external calls through a strict capability system, and bakes in safety, observability, and self-healing by default.
Core Concepts

Models — pure data shapes. Everything the system moves around is strongly typed.
Capabilities — declare what the agent can do (read files, make requests, etc), without giving it direct access.
Skills — small, focused behaviours that combine prompts, guardrails, and logic on top of capabilities.
Safety Substrate — the runtime’s guardrails. It controls execution, handles panics, manages degraded modes, and keeps things stable.

Repository Layout

src/core/ — core types and contracts
src/primitives/ — reusable building blocks
src/skills/ — reusable agent behaviours
src/stratum2/ — planning and execution (Stratum 2)
docs/architecture/ — deep technical docs

Inspector Dashboard
-------------------
The Stratum-2 Inspection Dashboard is a read-only, developer-facing TUI for visualizing agent cycle traces and memory substrate state in real time. It provides a safe, side-effect-free way to inspect agent activity and health.

Usage:
    python -m tools.inspector.dashboard

Optional arguments allow you to specify a trace directory or enable live watching.


Developer Tools
---------------

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
    python run_cycle.py "your request" --backend simulation
    python run_cycle.py "your request" --backend real_llm --verbose

Options:
    --backend, -b     "simulation" (deterministic mock) or "real_llm" (DeepSeek)
    --verbose, -v     Print full details (PromptRequest, PromptResponse, S2 updates)
    --silent          Suppress trace printing
    --example, -e     Use built-in example request


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