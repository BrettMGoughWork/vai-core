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

Interactive REPL (read-eval-print loop) for the full S2 pipeline: **plan → breakage detection → repair**. Remembers conversation context across turns. Primary manual testing interface for Release 0.1→1.0.

```
# Start with MockLLM (deterministic, default)
python tools/testing_harness/repl_harness.py --mock

# Or just:
python tools/testing_harness/repl_harness.py
```

REPL commands: `<prompt>` (run pipeline), `:history`, `:plans`, `:context`, `:clear`, `:help`, `:quit`

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