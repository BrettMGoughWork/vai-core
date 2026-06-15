`vai-core` is a clean, deterministic agent runtime built for clarity and long-term maintainability.

*Note: this project is currently in early development*

It’s built around a small set of stable concepts — models, capabilities, skills, and a safety substrate — that keep the system predictable even as you extend it.

The core idea is simple: give LLMs structured jobs, not free rein. The runtime forces clean JSON output, mediates all external calls through a strict capability system, and bakes in safety, observability, and self-healing by default.

---

## 🏗️ Architecture

vai-core is organised into six strata (S1–S6) plus a Gateway layer with strict dependency rules:

```
  External world (CLI, HTTP, WebSocket, webhook, cron, timer)
         │
         ▼
  Gateway ── (ingress/egress, channels, FastAPI, transport, S5 interface)
         │
         ▼
  S4 ── Platform (job system, queue, worker pool, supervision, event substrate,
  │               durability, config, security, observability)
  │
  ├──────────────────┐
  ▼                  ▼
  S5 Agents        S6 Workflow Engine
  (agent registry,  (trigger router, workflow state machine,
   activation,       agent selection, user interaction,
   routing,          instance store, WorkflowOps:
   strategy skills,   list, cancel, retry, dead-letter
   cognitive loop)    queue, metrics)
  │                  │
  └──────┬───────────┘
         ▼
  S3 ── Capabilities (primitives, skills, registry, quarantine, safety)
         │
         ▼
  S2 ── Strategy (planning, cognition — pure function, no I/O)
         │
         ▼
  S1 ── Runtime (execution engine, retry, panic guard, degraded mode)
```

**Key invariants:**
- **Gateway is the single entry point**. Channels live in the gateway — they normalise inbound events into ChannelMessages and forward them to S4. Gateway interfaces with S5 for dispatch. No knowledge of workflows or S6.
- **S4 is the universal job system**. It wraps everything in jobs for reliable execution, durability, and future fan-in/fan-out. S4 never owns cognition or workflow logic.
- **S6 owns workflow orchestration**. Trigger router maps events to workflows, engine runs the state machine, WorkflowOps provides cross-instance management — list, cancel, retry, dead-letter queue, and metrics.
- **Workflow instance state is persisted**. Every mutation in the engine's state machine is saved to WorkflowInstanceStore automatically by the agent supervisor.
- **S2 is pure**. No I/O, no tool calls, no side effects. Identical inputs → identical outputs.
- **S4 must not depend on S2, S5, or S6**. Platform is infrastructure — it cannot import cognition or agent layers.
- **Config is immutable after load**. Frozen at startup, never mutated at runtime.
- **No silent fallback**. Every code path either succeeds or fails explicitly.

See [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) for the full architecture.

---

## 📡 Channels

`vai-core` uses a channel abstraction (Stratum-4) to decouple ingress/egress from runtime logic.
Each channel implements the `Channel` protocol — `receive()`, `normalize()`, `send()` — and is
registered in a `ChannelRegistry` for transport-agnostic dispatch.

### CLI Channel

The CLI channel converts raw terminal input into canonical ChannelMessages and renders outbound
S4 payloads as human-readable text structures.

Key features:
- Deterministic, pure-logic adapter (no argparse, no stdout writes)
- `receive()` — dict with `text` + optional `sender` → `InboundChannelMessage`
- `normalize()` → canonical S4 job payload (`input` / `metadata`)
- `send()` → CLI-friendly dict (`text` / `metadata`)

Entry point:
```
# Single command
python -m tools.channels.cli_app "deploy the app" --sender alice

# Interactive mode (type commands, Ctrl+C to exit)
python -m tools.channels.cli_app

# Pipe mode
echo "list jobs" | python -m tools.channels.cli_app
```

### Web Channel

The Web channel converts structured HTTP JSON bodies into ChannelMessages and renders
outbound S4 payloads as transport-agnostic HTTP response structures. Pure logic only — no
FastAPI, no routing, no network IO.

Key features:
- Deterministic, pure-logic adapter (no FastAPI dependency)
- Pydantic models: `WebRequest` (`input`, `sender`, `metadata`) and `WebResponse` (`output`, `metadata`)
- `receive()` — dict with `input` + optional `sender` / `metadata` → `InboundChannelMessage`
- `normalize()` → canonical S4 job payload (merges channel metadata with user metadata)
- `send()` → HTTP-friendly dict (`output` / `metadata`)
- `handle_web_request()` — gateway convenience for FastAPI route handlers

Entry point:
```
python -m tools.channels.web_app
```

Friendly UI at `http://localhost:8000/`:
- Ingress pipeline form — enter text + sender → see the S4 job payload
- Egress pipeline form — enter output + metadata → see the HTTP-friendly response
- Channel inspector — live view of registered channels
- Service status bar with health indicator and channel count

API endpoints:
- `POST /api/ingress` — HTTP JSON body → S4 job payload (ingress pipeline)
- `POST /api/egress` — S4 payload → HTTP-friendly response (egress pipeline)
- `GET /api/inspect` — Show registered channels
- `GET /health` — Health check
- `GET /` — Friendly demo UI (this page)

### WebSocket Channel

The WebSocket channel converts structured WebSocket frames into ChannelMessages and
renders outbound S4 payloads as frame-friendly output structures. Pure logic only — no
WebSocket server, no event loop, no network IO.

Key features:
- Deterministic, pure-logic adapter (no async, no event-loop dependency)
- Supports `message_type` field (`"text"`, `"binary"`, …) for frame-type awareness
- `receive()` — dict with `text` + optional `sender` / `message_type` → `InboundChannelMessage`
- `normalize()` → canonical S4 job payload (`input` / `metadata` with channel, sender, message_type)
- `send()` → WebSocket-friendly dict (`text` / `message_type` / `metadata`)
- `handle_ws_message()` — gateway convenience for WebSocket server handlers

Entry point (programmatic):
```python
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.ws import register_websocket_channel
from src.gateway.entrypoint import process_channel_input

# Register
registry = ChannelRegistry()
register_websocket_channel(registry)

# Ingress
payload = process_channel_input(registry, "ws", {"text": "hello", "sender": "node1"})
# {"input": "hello", "metadata": {"channel": "ws", "sender": "node1", "message_type": "text"}}

# Egress
from src.gateway.channels.ws import WebSocketChannel
channel = WebSocketChannel()
output = channel.send({"output": "Ack", "metadata": {"job_id": "j-1"}})
# {"text": "Ack", "message_type": "text", "metadata": {"job_id": "j-1"}}
```

### Webhook Channel

The Webhook channel accepts arbitrary inbound POST payloads from external services
(WhatsApp, Telegram, GitHub, Stripe, Twilio, Slack, Discord, custom integrations) and
normalises them into ChannelMessages. Pure logic only — no FastAPI, no routing, no
signature verification, no network IO.

Key features:
- Deterministic, pure-logic adapter (no IO, no framework dependency)
- `WebhookEvent` frozen dataclass — canonical event model (`source`, `payload`, `sender`)
- `receive()` — dict with `source` + `payload` + optional `sender` → `InboundChannelMessage`
- `normalize()` → canonical S4 job payload (`input` = raw payload dict, `metadata` includes source)
- `send()` → webhook-compatible dict (`status: "ok"` / `response` / `metadata`)
- `handle_webhook_post()` — gateway convenience for FastAPI webhook route handlers

Entry point (programmatic):
```python
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.webhook import register_webhook_channel
from src.gateway.entrypoint import process_channel_input

# Register
registry = ChannelRegistry()
register_webhook_channel(registry)

# Ingress (GitHub push event)
payload = process_channel_input(registry, "webhook", {
    "source": "github",
    "payload": {"event": "push", "ref": "main", "commits": [...]},
    "sender": "github-bot",
})
# {"input": {"event": "push", "ref": "main", "commits": [...]},
#  "metadata": {"channel": "webhook", "source": "github", "sender": "github-bot"}}

# Ingress (WhatsApp message)
payload = process_channel_input(registry, "webhook", {
    "source": "whatsapp",
    "payload": {"from": "+1234567890", "text": "Hello"},
})
# {"input": {"from": "+1234567890", "text": "Hello"},
#  "metadata": {"channel": "webhook", "source": "whatsapp", "sender": None}}

# Egress
from src.gateway.channels.webhook import WebhookChannel
channel = WebhookChannel()
output = channel.send({"output": "Processed", "metadata": {"job_id": "j-1"}})
# {"status": "ok", "response": "Processed", "metadata": {"job_id": "j-1"}}
```

Supported source identifiers: `whatsapp`, `telegram`, `github`, `stripe`, `twilio`,
`slack`, `discord`, `generic`.

---

## 🎯 Usage Examples

### CLI Channel

**Runnable entry point:**
```
# Single command
python -m tools.channels.cli_app "deploy the app" --sender alice

# Interactive mode (type commands, Ctrl+C to exit)
python -m tools.channels.cli_app

# Pipe mode
echo "list jobs" | python -m tools.channels.cli_app
```

**Programmatic usage:**

```python
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.cli import register_cli_channel
from src.gateway.entrypoint import process_channel_input

# Register
registry = ChannelRegistry()
register_cli_channel(registry)

# Ingress
payload = process_channel_input(registry, "cli", {"text": "deploy the app", "sender": "alice"})
# {"input": "deploy the app", "metadata": {"channel": "cli", "sender": "alice", "received_at": ...}}

# Egress
from src.gateway.channels.cli import CLIChannel
channel = CLIChannel()
output = channel.send({"output": "Done!", "metadata": {"job_id": "j-1"}})
# {"text": "Done!", "metadata": {"job_id": "j-1"}}
```

### Web Channel

**Runnable entry point (start server, then curl):**
```
# Terminal 1: Start the service
python -m tools.channels.web_app

# Terminal 2: Ingress — send a request through the web pipeline
curl -X POST http://localhost:8000/api/ingress \
  -H "Content-Type: application/json" \
  -d '{"input": "deploy the app", "sender": "alice"}'

# Egress — convert S4 payload back to HTTP-friendly response
curl -X POST http://localhost:8000/api/egress \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-token" \
  -d '{"output": "Deploying...", "metadata": {"job_id": "j-1"}}'

# Inspect registered channels
curl http://localhost:8000/api/inspect

# Health check
curl http://localhost:8000/health
```

**Programmatic usage:**

```python
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.web import register_web_channel
from src.gateway.entrypoint import handle_web_request

# Register
registry = ChannelRegistry()
register_web_channel(registry)

# Ingress (as called by a FastAPI route handler)
payload = handle_web_request(registry, {"input": "deploy", "sender": "api-key-123"})
# {"input": "deploy", "metadata": {"channel": "web", "sender": "api-key-123"}}

# Egress
from src.gateway.channels.web import WebChannel
channel = WebChannel()
response = channel.send({"output": "Deploying...", "metadata": {"job_id": "j-1"}})
# {"output": "Deploying...", "metadata": {"job_id": "j-1"}}

# Validate with Pydantic models
from src.gateway.channels.web import WebRequest, WebResponse
req = WebRequest(input="deploy", sender="alice")
resp = WebResponse(output="ok", metadata={"job_id": "j-1"})
```

---

## 🚀 Interactive REPL

The project includes a live REPL for development — a direct line into the S2 planner, skill
execution, and breakage repair loop.

```
# Real LLM (default — set LLM_PROVIDER + LLM_MODEL env vars)
python -m tools.testing_harness.repl_harness

# Mock LLM (deterministic, no API calls)
python -m tools.testing_harness.repl_harness --mock
```

Each turn at the `s2>` prompt runs: **plan → breakage detection → repair → execute skills**.
Conversation context is remembered across turns. Type `:help` for all commands.

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

## 📁 Repository Layout

```
src/
├── gateway/         (Gateway) Ingress/egress, channels, FastAPI, transport, S5 interface
├── runtime/         (S1) Execution engine, pipeline, retry, panic guard, degraded mode
├── strategy/        (S2) Planning, cognition, memory — pure function, no I/O
├── capabilities/    (S3) Primitives, skills, registry, safety validators, quarantine
├── platform/        (S4) Job system, queue, worker pool, supervision, config, security,
│                         observability, deployment, daemon
├── agent/           (S5/S6) Agent registry, activation, routing, strategy skills,
│   │                       workflow engine, trigger router, WorkflowOps
│   └── workflow/    (S6) Workflow engine, instance store, WorkflowOps
└── release/             Release checklist and gating
docs/
├── architecture/   ARCHITECTURE.md, BOUNDARIES.md, ROADMAP.md, control plane, worker pool, ...
├── api/            API documentation per component
├── channels/       Channel documentation per transport
└── lifecycle/      Lifecycle state machines
tools/              Developer tooling, testing harness, channels CLIs, quarantine CLI
tests/
├── unit/           Fast, isolated tests per component
└── integration/    Cross-module end-to-end tests
```

### Quick reference

| Path | Responsibility |
|---|---|
| `src/gateway/` | Gateway — ingress/egress, channels, FastAPI, transport, S5 interface |
| `src/runtime/` | S1 — execution substrate, pipeline, retry/recovery, panic guard |
| `src/strategy/` | S2 — cognitive planning (pure, no I/O) |
| `src/capabilities/primitives/` | S3 — reusable building blocks (Python, CLI, MCP) |
| `src/capabilities/skills/` | S3 — reusable agent behaviours |
| `src/capabilities/registry/` | S3 — registries, loaders, safety validators, quarantine |
| `src/platform/config/` | S4 — configuration system (env, file, overrides) |
| `src/platform/security/` | S4 — auth, rate limiting, input validation, sandbox |
| `src/platform/deployment/` | S4 — local and container deployment targets |
| `src/platform/daemon/` | S4 — daemon entrypoint, instruction dispatch |
| `src/release/` | S4 — release checklist and gating |
| `src/agent/workflow/` | S6 — workflow engine, loaders, trigger router, instance store, WorkflowOps |
| `docs/architecture/` | Architecture documentation |
| `docs/api/` | API documentation |
| `docs/channels/` | Channel documentation |



## Developer Tools


### Operator Console (TUI Dashboard)

The Operator Console is a read-only operational dashboard for monitoring Stratum-4 runtime
state. Built with `textual`, it displays real-time views of workers, jobs, scheduling, and
heartbeats — without any channel adapter logic.

This is an **operational developer tool**, separate from the channel abstraction. It consumes
the same data models that the runtime produces but does not slot into the ingress/egress
pipeline.

```
python -m tools.channels.tui_app
```

Key features:
- Four live panels: WORKERS, JOBS, SCHEDULING, HEARTBEATS
- Colour-coded status indicators (active/inactive/failed)
- Keybindings: `q` quit, `r` refresh
- Pure-logic data models shared with the runtime adapter layer
- Zero network, queue, or persistence coupling


### DevSMTPTransport (Development Email)

`DevSMTPTransport` is a pluggable **SMTP-based** email transport that sends system alerts to a
local SMTP test service — no real SMTP, DKIM, SPF, or DMARC required.

It connects via SMTP to a configurable host:port, making it compatible with
[MailHog](https://github.com/mailhog/MailHog) (``localhost:1025`` — the opinionated default)
and [smtp4dev](https://github.com/rnwood/smtp4dev) (``localhost:25``) out of the box.
A real SMTP relay can also be pointed to (e.g. ``smtp.example.com:587``).

```python
from src.platform.transport import DevSMTPConfig, DevSMTPTransport

config = DevSMTPConfig(host="localhost", port=1025)
transport = DevSMTPTransport(config)

result = transport.send(
    to="admin@example.com",
    subject="System alert: disk 90% full",
    body="The /dev/sda1 partition is at 90% capacity.",
)
```

Configuration via ``DevSMTPConfig``:

| Attribute | Default | Description |
|-----------|---------|-------------|
| ``host`` | ``localhost`` | SMTP server hostname. |
| ``port`` | ``1025`` | SMTP server port. MailHog default is ``1025``; smtp4dev uses ``25``. |
| ``sender`` | ``alerts@vai-core.local`` | Default ``From`` address. |
| ``timeout`` | ``5.0`` | SMTP connection timeout (seconds). |

**Note:** [MailHog](https://github.com/mailhog/MailHog) is the opinionated choice for local
testing. It can be replaced with [smtp4dev](https://github.com/rnwood/smtp4dev) or a real
SMTP service by updating ``host`` and ``port``.

View captured messages at the MailHog web UI: **http://localhost:8025**

To start MailHog manually:
```powershell
# SMTP on :1025, HTTP UI on :8025
.\tools\dev\MailHog.exe
```


### AlertNotification (Mail by default)

``AlertNotifier`` is the runtime alert delivery system.  It routes severity-gated
alerts through the configured transport — by default via ``DevSMTPTransport``
(MailHog on ``localhost:1025``).  Alerts below the configured ``min_level`` are
silently dropped.

```python
from src.platform.runtime.alerting import AlertNotifierConfig, AlertNotifier
from src.platform.transport import DevSMTPConfig, DevSMTPTransport

config = AlertNotifierConfig(
    recipient="ops@example.com",
    min_level="warning",   # info / warning / error / critical
    sender="noreply@vai-core.local",
)
transport = DevSMTPTransport(DevSMTPConfig())
notifier = AlertNotifier(config, transport)

# Sends (level >= warning)
notifier.alert("Disk 90% full", "/dev/sda1 at 90%", level="critical")

# Skipped (info < warning)
notifier.alert("Routine check", "All healthy", level="info")
```

The notification recipient is configured via the ``AlertNotifierConfig.recipient``
field — this is where all system alerts are delivered.

``notify_on_dispatch`` composes the notifier with the instruction dispatcher
so daemon actions (panic, fail, degrade, etc.) automatically produce alerts:

```python
from src.platform.runtime.alerting import notify_on_dispatch
from src.platform.daemon.instruction_dispatch import default_dispatcher

action, event, alert = notify_on_dispatch(
    {"type": "PanicInstruction", "reason": "OOM detected"},
    default_dispatcher().dispatch,
    notifier,
    subject_prefix="[S4]",
)
```


### Inspector Dashboard

The Stratum-2 Inspection Dashboard is a read-only, developer-facing TUI for visualizing agent cycle traces and memory substrate state in real time. It provides a safe, side-effect-free way to inspect agent activity and health.

Usage:
    python -m tools.inspector.dashboard

Optional arguments allow you to specify a trace directory or enable live watching.


### Observability Dashboard (S4.8.5)

The S4 Observability Dashboard is a read-only **web UI** for monitoring Stratum‑4 runtime state in real time. It consumes S4's existing observability events (metrics, traces, logs, health checks) via stdin or file pipe — never importing or modifying S4 internals.

```powershell
# Pipe live S4 output directly into the dashboard
python -m tools.channels.cli_app | python -m src.platform.observability.dashboard

# Or replay a recorded session from a JSONL file
python -m src.platform.observability.dashboard --from-file events.jsonl
```

The dashboard opens at **http://localhost:8765** with four live panels:

| Panel | Content |
|-------|---------|
| Jobs | job_id, type, state, retries, age, worker assignment |
| Workers | worker_id, status, last heartbeat, restart count, active job |
| Traces | Hierarchical tree: per-job → per-cycle → per-segment with durations |
| Metrics | Job counts, queue depth, worker health, execution time histogram, drift frequency |

Key features:
- **SSE live streaming** — panels update as events arrive, with 15s keepalive
- **Poll fallback** — auto-reconnects on SSE disconnect (3s interval)
- **Dark theme** — deterministic, read-only
- **Zero external dependencies** — pure Python stdlib (`http.server`, `json`, `threading`)
- **Configurable** — `--host`, `--port`, `--max-events` for the event ring buffer


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


### Deployment Targets (S4.9.2)

Stratum-4 supports two deployment targets: **local** and **container**.
Cloud deployment is acknowledged but intentionally deferred.

**Local mode** runs S4 directly as a bare Python process:

```powershell
python -m src.platform.deployment --mode local
```

**Container mode** packages S4 as a single OCI image:

```powershell
# Build
docker build -t s4:latest .

# Run
docker run --rm -it s4:latest
```

The image is pinned to `python:3.12-slim-bookworm`, logs to stdout/stderr,
and handles SIGTERM for graceful shutdown. Configuration is driven entirely
by environment variables via the S4.9.1 Config System (`S4_` prefix).

Entrypoint: `/entrypoint.sh` → `python -m src.platform.deployment --mode container`