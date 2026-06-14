## Overview

This document describes every developer tool in the repository. All tools live under `tools/` and are designed to be run directly via `python -m tools.<module>` or `python tools/<path>.py`.

---

## Architecture Tools (`tools/architecture/`)

Tools for structural extraction, audit, and CI enforcement.

### `extract_architecture.py`

Deterministic structural extraction of the vai-core repo. Produces `docs/architecture.json` (packages, classes, references). Idempotent — always overwrites.

```
python tools/architecture/extract_architecture.py
```

### `audit.py`

Reads `docs/architecture.json` and produces `docs/architecture_audit.md`. Checks for duplicate classes, forbidden cross-stratum imports, stratum invariant violations, dead code (fan_in == 0), and priority-ranked issues.

```
python tools/architecture/audit.py
```

### `ci_architecture_check.py`

CI wrapper — runs extraction then audit sequentially. Exits non-zero if any critical or high-severity issues are found.

```
python tools/architecture/ci_architecture_check.py
```

---

## Fetch Harness (`tools/fetch_harness/`)

Scenario-driven test harness for the HTTP fetch subsystem.

### `harness.py`

Loads scenarios from `scenarios.json`, executes real HTTP fetches through the full `fetch_url` orchestrator pipeline (mode selection → execution → signal extraction → fallback → sanitisation), and reports success metrics.

```
# List available scenarios
python -m tools.fetch_harness.harness --list

# Run all scenarios
python -m tools.fetch_harness.harness

# Filter by hardness level (simple / hardened / javascript / spa / antibot)
python -m tools.fetch_harness.harness --hardness simple

# Run a single scenario with JSON output
python -m tools.fetch_harness.harness --name httpbin_get --json

# Quick-add a new scenario
python -m tools.fetch_harness.harness --add "mysite,https://example.com,simple"
```

Options: `--hardness` / `-H`, `--name` / `-n`, `--timeout` / `-t` (seconds, default 10), `--json` / `-j`, `--list` / `-l`, `--add` / `-a`

---

## Inspector Dashboard (`tools/inspector/`)

Read-only, developer-facing TUI (Textual) for visualizing agent cycle traces and memory substrate state.

### `dashboard.py`

Main entry point — launches the inspector TUI.

```
python -m tools.inspector.dashboard
python -m tools.inspector.dashboard --trace-dir /path/to/agent_traces
```

Options: `--trace-dir` (default: `agent_traces/`)

### Supporting modules (import-only)

| Module | Purpose |
|--------|---------|
| `diff_engine.py` | Deep JSON diff engine for cycle trace comparison |
| `file_watcher.py` | `TraceDirectoryWatcher` — polls for new `cycle_*.json` files |
| `panels/cycle_list.py` | Scrollable cycle list with status badges (OK/DRIFT/REPAIRS/ERROR) |
| `panels/cycle_details.py` | Expanded cycle view — transitions, drift, repairs, errors |
| `panels/memory_inspector.py` | Tabbed memory snapshot: Subgoals, Segments, Plans, Drift, Reflection |
| `panels/health_summary.py` | Compact footer with aggregate run metrics |

---

## Observability Dashboard (`src/platform/observability/dashboard/`)

Read-only web UI for monitoring Stratum‑4 runtime state in real time. Consumes S4 observability events (metrics, traces, logs, health) via stdin pipe or JSONL file replay — never modifies S4 internals.

### `__init__.py` (entry point)

Launches the dashboard as a standalone HTTP server with SSE streaming.

```powershell
# Pipe live S4 CLI output
python -m tools.channels.cli_app | python -m src.platform.observability.dashboard

# Replay recorded events
python -m src.platform.observability.dashboard --from-file events.jsonl

# Custom host/port
python -m src.platform.observability.dashboard --host 0.0.0.0 --port 8080
```

Options: `--mode` (default `web`), `--from-file`, `--host` (`127.0.0.1`), `--port` (`8765`), `--max-events` (`10000`)

### Supporting modules (import-only)

| Module | Purpose |
|--------|---------|
| `event_model.py` | `DashboardEventStore` — thread-safe in-memory state, event ingestion, trace tree assembly, SSE subscriber system |
| `web_server.py` | `DashboardWebServer` — HTTP routes (`/api/state`, `/api/summary`, `/api/events/stream`, `/api/events/recent`) and static file serving |
| `static/index.html` | Single-page dark-theme frontend: Job List, Worker List, Trace Tree, Metrics panels with SSE + polling fallback |

### Dashboard panels

| Panel | Data |
|-------|------|
| Jobs | job_id, type, state, retries, age, worker assignment |
| Workers | worker_id, status, last heartbeat, restarts, active job |
| Traces | Expandable per-job/per-cycle/per-segment tree with durations, drift/repair markers |
| Metrics | Job counts, queue depth, execution time histogram (5 buckets), drift frequency |

---

## Testing Harness (`tools/testing_harness/`)

End-to-end and plumbing test tools for the agent pipeline.

### `e2e_harness.py`

Full Prompt → LLM → Planner → Skill pipeline. Sends a user prompt through a real (or mock) LLM, runs skill discovery, plan generation, and skill execution — all observable end-to-end.

```
# Real LLM (default)
python -m tools.testing_harness.e2e_harness "echo back: hello world"

# Mock LLM (deterministic, no API calls)
python -m tools.testing_harness.e2e_harness "echo test" --backend mock

# JSON output
python -m tools.testing_harness.e2e_harness "list files" --json
```

Options: `prompt` (positional), `--backend` (`real_llm` | `mock`, default `real_llm`), `--json`

### `run_cycle.py`

Single-cycle debug runner for the S2 ↔ S1 ↔ LLM boundary. Runs exactly ONE cycle — useful for debugging prompt construction, schema validation, and state transitions.

```
python tools/testing_harness/run_cycle.py "your request" --backend simulation
python tools/testing_harness/run_cycle.py "your request" --backend real_llm --verbose
```

Options: `request` (positional), `--backend` (`simulation` | `real_llm`, default `simulation`), `--verbose` / `-v`, `--silent`, `--example` / `-e`

### `plan_repair_harness.py`

Deterministic, stdin-driven CLI for exercising the structural repair pipeline on plans, segments, and subgoals. Accepts malformed JSON and prints a full state-transition trace. Never calls an LLM — pure and deterministic.

```
python tools/testing_harness/plan_repair_harness.py < input.json
```

### `signal_harness.py`

Deterministic, stdin-driven CLI for end-to-end validation of the full drift-to-repair pipeline: signals → classification → arbitration → action → budget update. Never calls an LLM.

```
python tools/testing_harness/signal_harness.py < signals.json
```

### `repl_harness.py`

Interactive REPL (read-eval-print loop) for the full S2 pipeline: **plan → breakage detection → repair → execute**. Remembers conversation context across turns (prior prompts and execution outputs are fed back to the LLM). Primary manual testing interface for Release 0.1→1.0.

```
# Start with real LLM (default; set LLM_PROVIDER + LLM_MODEL env vars)
python -m tools.testing_harness.repl_harness

# Plan-only mode — skip skill execution
python -m tools.testing_harness.repl_harness --no-execute

# Start with MockLLM (deterministic, no API calls)
python -m tools.testing_harness.repl_harness --mock
```

REPL commands: `<prompt>` (run pipeline), `:history`, `:plans`, `:context`, `:clear`, `:help`, `:quit`

### `s4_mvp_harness.py`

Scenario-driven integration test harness for the Stratum-4 Phase 4.1 Minimal Execution Path. Exercises each S4 component — Gateway, Normalization, Job, Queue, Worker, Adapter, Job Store, and Logging — in isolation plus the full end-to-end pipeline. Does not import from S1/S2/S3.

*Invariants*:
- S4 must remain operational, deterministic, isolated, and free of cognitive logic.
- Platform stratum must be strictly isolated from other strata (S4 may orchestrate S1/S2/S3, but it must never reach into them).
- Components within S4 should be isolated from each other where possible (each S4 subsystem should be independently testable, replaceable, and composable).
- Platform lives in `/src/platform`.
- S4 orchestrates execution but never performs reasoning.

```
# Run all 11 scenarios
python -m tools.testing_harness.s4_mvp_harness

# Run a single scenario by name
python -m tools.testing_harness.s4_mvp_harness --name end_to_end

# JSON output (machine-readable)
python -m tools.testing_harness.s4_mvp_harness --json

# List available scenarios
python -m tools.testing_harness.s4_mvp_harness --list
```

Available scenarios: `normalization`, `job_creation`, `queue_fifo`, `job_store`, `worker_empty`, `worker_execute`, `adapter`, `logging`, `end_to_end`, `gateway_post`, `gateway_get`, `dashboard`, and 47 more (59 total — run `--list` for full list)

Options: `--name` / `-n`, `--json` / `-j`, `--list` / `-l`

Uses `FastAPI TestClient` for gateway scenarios and direct imports for all other scenarios. Scenarios share the module-level `app` singleton — `gateway_get` drains leftover queue state from prior tests to avoid interference.

---

## Custom Utilities (`tools/custom/`)

Developer convenience scripts — not part of the formal toolchain.

| File | Purpose |
|------|---------|
| `debug.bat` | Debug helper for locating the `.env` file |
| `toggle-deepseek.bat` | Environment toggle placeholder (requires companion `toggle-deepseek.py`) |

---

## Design Principles

All tools follow these principles:

- **Local-first** — designed to run without external dependencies beyond the project.
- **Fast feedback** — intended for frequent use during development.
- **Opinionated by design** — enforce conventions rather than merely suggesting them.
- **Extensible** — new tools integrate into the same `tools.*` structure.

### Usage Guidelines

- Run `ci_architecture_check.py` before opening a PR.
- Run the fetch harness to verify HTTP pipeline health after changes to the fetch subsystem.
- Use `e2e_harness.py` to validate the full S3 → S2 → S1 boundary before releases.
- Use `repl_harness.py` for interactive manual testing of the S2 plan-detect-repair pipeline.
- Use `run_cycle.py` for focused debugging of a single LLM interaction.
- Treat violations as signals, not suggestions.
- Extend tooling when patterns become repetitive.