"""
Web Channel Application — FastAPI with Gateway → S5 handoff.

Demonstrates the correct architectural flow::

    HTTP JSON body → Channel.normalize() → submit_channel_input() → S5 Supervisor

Usage::

    python -m tools.channels.web_app

Then::

    curl -X POST http://localhost:8000/run \
        -H "Content-Type: application/json" \
        -d '{"input": "deploy the app"}'

    curl http://localhost:8000/health
"""

from __future__ import annotations

import logging
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request

from starlette.responses import FileResponse

from src.agent.composition_root import (
    agent_registry,
    pattern_registry,
    s5_adapter,
    state_store,
    workflow_registry,
)
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.web import WebChannel, WebRequest, register_web_channel
from src.gateway.channels.web_simple import mount_ui
from src.gateway.entrypoint import submit_channel_input

# ---------------------------------------------------------------------------
# S5 Supervisor wiring — uses the shared composition root
# ---------------------------------------------------------------------------
# The composition_root already loads agents from config/agents/, builds the
# real LLM transport, and wires the full S5 pipeline (workflow engine,
# tool adapters, strategy router, todo orchestrator, etc.).
#
# We reuse ``s5_adapter`` directly — this is the same adapter the CLI
# channel and production transport app use.

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("web_channel")

# Session-scoped agent selection (mirrors CLI's ``/agent <id>``).
# Defaults to the system default agent; changed at runtime via /agent.
_current_agent_id: str = "default-agent"

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

# Wire up the Web channel at import time so the registry is ready
registry = ChannelRegistry()
register_web_channel(registry)

app = FastAPI(
    title="VAI — Web Channel (Gateway → S5)",
    version="0.2.0",
    description=(
        "Demonstrates the Gateway → S5 Supervisor handoff. "
        "Receives structured HTTP JSON bodies, normalises them via the "
        "WebChannel, and hands off to the S5 Supervisor for processing."
    ),
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check."""
    channel_names = registry.names
    return {
        "status": "ok",
        "service": "vai-web-channel",
        "channels": channel_names,
    }


@app.post("/run")
async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept a JSON payload, normalise it, and hand off to S5.

    This is the primary endpoint used by the PWA web UI.

    Slash commands (mirroring the CLI channel):
      ``/agent``          — show current agent
      ``/agent <id>``     — switch to a different agent
      ``/agents``         — list all registered agents
      ``/workflow <id>``  — show a specific workflow
      ``/workflows``      — list all registered workflows
      ``/patterns``       — list all registered patterns
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    text: str = payload.get("input", "")
    global _current_agent_id

    # ── Slash commands ──────────────────────────────────────────────────
    if text.startswith("/"):
        cmd = text.strip().lower()

        if cmd == "/agents":
            return {
                "output": _format_agents_list(),
                "reply": _format_agents_list(),
                "type": "slash_command",
            }

        if cmd == "/agent":
            return {
                "output": _format_current_agent(),
                "reply": _format_current_agent(),
                "type": "slash_command",
            }

        if cmd.startswith("/agent "):
            agent_id = cmd[7:].strip()
            if not agent_registry.has_agent(agent_id):
                return {
                    "output": f"Unknown agent: {agent_id!r}\nUse /agents to see available agents.",
                    "reply": f"Unknown agent: {agent_id!r}\nUse /agents to see available agents.",
                    "type": "slash_command",
                    "error": True,
                }
            _current_agent_id = agent_id
            return {
                "output": _format_current_agent(),
                "reply": _format_current_agent(),
                "type": "slash_command",
            }

        if cmd == "/workflows":
            return {
                "output": _format_workflows_list(),
                "reply": _format_workflows_list(),
                "type": "slash_command",
            }

        if cmd.startswith("/workflow "):
            wf_id = cmd[10:].strip()
            wf = workflow_registry.get(wf_id)
            if wf is None:
                return {
                    "output": f"Unknown workflow: {wf_id!r}\nUse /workflows to see available workflows.",
                    "reply": f"Unknown workflow: {wf_id!r}\nUse /workflows to see available workflows.",
                    "type": "slash_command",
                    "error": True,
                }
            return {
                "output": _format_workflow_detail(wf),
                "reply": _format_workflow_detail(wf),
                "type": "slash_command",
            }

        if cmd == "/patterns":
            return {
                "output": _format_patterns_list(),
                "reply": _format_patterns_list(),
                "type": "slash_command",
            }

        # Unknown slash command — fall through to S5 as regular input
        # so the agent can explain what commands are available.

    # ── Regular input → S5 pipeline ────────────────────────────────────
    result = submit_channel_input(registry, "web", payload, adapter=s5_adapter, agent_id=_current_agent_id)

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return {
        "output": result.get("reply", ""),
        "metadata": result.get("metadata", {}),
        "agent_id": result.get("agent_id", _current_agent_id),
        "reply": result.get("reply", ""),
    }


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    """Poll job status — used by the PWA for async responses."""
    agent_state = state_store.load(job_id)
    if agent_state is None:
        raise HTTPException(status_code=404, detail="not found")

    return {
        "job_id": job_id,
        "state": agent_state.lifecycle_state.value,
        "output": getattr(agent_state, "last_reply", None),
        "result": getattr(agent_state, "last_metadata", None),
    }


@app.post("/api/ingress")
async def api_ingress(
    body: WebRequest,
    request: Request,
    authorization: str | None = Header(None),
) -> dict[str, Any]:
    """
    Normalise incoming HTTP JSON and hand off to the S5 Supervisor.

    This is the **ingress** path: raw HTTP input → ChannelMessage
    → S5 adapter → S5 Supervisor for processing.
    """
    sender = body.sender or _resolve_sender(authorization)
    raw: dict[str, Any] = {"input": body.input, "sender": sender}
    if body.metadata:
        raw["metadata"] = body.metadata

    result = submit_channel_input(registry, "web", raw, adapter=s5_adapter, agent_id=_current_agent_id)

    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])

    logger.info("Ingress  | sender=%s  input=%s",
                sender, _truncate(body.input))
    return {
        "status": "accepted",
        "channel": "web",
        "result": result,
    }


@app.post("/api/egress")
async def api_egress(body: dict[str, Any]) -> dict[str, Any]:
    """
    Convert an outbound payload into an HTTP-friendly response.

    This is the **egress** path: outbound dict → transport-agnostic
    HTTP response body via the WebChannel's send().
    """
    channel = WebChannel()
    response = channel.send(body)
    logger.info("Egress   | output=%s", _truncate(response.get("output", "")))
    return {
        "status": "ok",
        "channel": "web",
        "response": response,
    }


@app.get("/api/inspect")
async def api_inspect() -> dict[str, Any]:
    """Show the registered channels and their types."""
    return {
        "registry": {
            name: type(channel).__name__
            for name in registry.names
            if (channel := registry.get(name))
        }
    }


# ---------------------------------------------------------------------------
# Root page — PWA Web UI (Sprint 13)
# ---------------------------------------------------------------------------


@app.get("/")
async def root():
    """Serve the PWA shell (index.html)."""
    from pathlib import Path as _Path

    ui_index = (
        _Path(__file__).resolve().parent.parent.parent
        / "src" / "gateway" / "channels" / "web_simple" / "ui" / "index.html"
    )
    return FileResponse(str(ui_index))


mount_ui(app)


# ---------------------------------------------------------------------------
# Slash-command formatters
# ---------------------------------------------------------------------------


def _format_current_agent() -> str:
    """Return a human-readable summary of the currently selected agent."""
    lines = [
        f"**Current agent:** `{_current_agent_id}`",
    ]
    if agent_registry.has_agent(_current_agent_id):
        meta = agent_registry.get_agent(_current_agent_id)
        ident = meta.identity
        lines.append(f"- Name: {ident.name}")
        lines.append(f"- Description: {ident.description}")
        if meta.persona:
            lines.append(f"- Persona: {meta.persona}")
        tools = meta.tools or []
        if tools and tools != ["*"]:
            lines.append(f"- Tools: {', '.join(tools)}")
    return "\n".join(lines)


def _format_agents_list() -> str:
    """Return a human-readable list of all registered agents."""
    lines = [f"**Registered agents** ({agent_registry.agent_count}):"]
    for meta in agent_registry.list_agents():
        ident = meta.identity
        marker = " ▶" if ident.agent_id == _current_agent_id else ""
        lines.append(f"- `{ident.agent_id}`{marker} — {ident.name}")
        if meta.persona:
            lines.append(f"  _Persona: {meta.persona}_")
    return "\n".join(lines)


def _format_workflows_list() -> str:
    """Return a human-readable list of all registered workflows."""
    defs = workflow_registry.list()
    lines = [f"**Registered workflows** ({len(defs)}):"]
    for wf in defs:
        desc = f" — {wf.description}" if wf.description else ""
        lines.append(f"- `{wf.workflow_id}`{desc}")
    return "\n".join(lines)


def _format_workflow_detail(wf) -> str:
    """Return a human-readable detail view for a single workflow."""
    lines = [
        f"**Workflow:** `{wf.workflow_id}`",
        f"- Description: {wf.description or '(none)'}",
    ]
    if hasattr(wf, "steps") and wf.steps:
        lines.append("- Steps:")
        for i, step in enumerate(wf.steps, 1):
            step_name = getattr(step, "name", f"step-{i}")
            lines.append(f"  {i}. {step_name}")
    return "\n".join(lines)


def _format_patterns_list() -> str:
    """Return a human-readable list of all registered patterns."""
    patterns = pattern_registry.list()
    lines = [f"**Registered patterns** ({len(patterns)}):"]
    for p in patterns:
        desc = f" — {p.description}" if p.description else ""
        lines.append(f"- `{p.pattern_id}`{desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_sender(authorization: str | None) -> str:
    """Resolve sender identity from an Authorization header."""
    if authorization and authorization.startswith("Bearer "):
        key = authorization.removeprefix("Bearer ")
        return f"api-key:{key}"
    return "anonymous"


def _truncate(text: str, max_len: int = 60) -> str:
    """Truncate long text for log messages."""
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

HOST = "0.0.0.0"
PORT = 8000


def main() -> None:
    print(f"  VAI - Web Channel PWA  (Sprint 13)")
    print(f"  -----------------------------")
    print(f"  Listening on http://{HOST}:{PORT}")
    print(f"  API docs   http://{HOST}:{PORT}/docs")
    print(f"  Health     http://{HOST}:{PORT}/health")
    print(f"  Chat UI    http://{HOST}:{PORT}/  (PWA)")
    print(f"\n  Channels: {registry.names}")
    print()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
