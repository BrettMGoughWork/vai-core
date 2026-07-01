"""FastAPI Gateway — Stratum-4 transport boundary with S5 handoff.

The Gateway imports a pre-wired ``s5_adapter`` from the S5 composition root
(``src.agent.composition_root``).  All adapter-wiring lives there so the
infrastructure stratum stays free of adapter imports.

The Gateway **never** imports S5 internals directly — it goes through the
adapter interface.

Usage::

    python -m src.platform.transport.app

Then::

    curl -X POST http://localhost:8000/run \\
        -H "Content-Type: application/json" \\
        -d '{"input": "hello"}'

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
    council_orchestrator,
    council_registry,
    pattern_registry,
    s5_adapter,
    state_store,
    supervisor,
    wf_registry,
)
from src.agent.contracts import AgentMessage
from src.agent.interfaces.agent_state import LifecycleState
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.web import WebChannel, WebRequest, register_web_channel
from src.gateway.channels.web_simple import mount_ui

# Module-level adapter so gateway stays lightweight
app = FastAPI(
    title="VAI — Stratum-4 Gateway",
    version="0.3.0",
    description=(
        "Stratum-4 transport boundary with S5 handoff. "
        "Routes normalise HTTP JSON bodies and hand off to the S5 Supervisor. "
        "Supports slash commands, agent chat, workflow execution, and council deliberation."
    ),
)

# Module-level channel registry (created once, not per-request)
_channel_registry = ChannelRegistry()
register_web_channel(_channel_registry)

# Session-scoped agent selection (mirrors CLI's ``/agent <id>``).
# Defaults to the system default agent; changed at runtime via /run /agent <id>.
_current_agent_id: str = "default-agent"

# Logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("gateway")

# Mount the Web Channel UI (PWA) — serves index.html at "/" and static assets at "/static"
mount_ui(app)


@app.post("/run")
async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept a JSON payload, normalise it, and hand off to S5.

    The payload is normalised through the channel pipeline, wrapped as an
    ``AgentRequest``, and processed by the S5 Supervisor.

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

    from src.gateway.entrypoint import submit_channel_input

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
            wf = wf_registry.get(wf_id)
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
    result = submit_channel_input(
        _channel_registry, "web", payload, adapter=s5_adapter, agent_id=_current_agent_id,
    )

    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    return {
        "output": result.get("reply", ""),
        "metadata": result.get("metadata", {}),
        "agent_id": result.get("agent_id", _current_agent_id),
        "reply": result.get("reply", ""),
    }


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    """Retrieve a job's state and result by its ``job_id``. (legacy)

    Returns ``404`` with a JSON error body if the job is not found.
    This endpoint exists for backward compatibility and returns
    agent state info for the given id.
    """
    state = state_store.load(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="not found")

    return {
        "job_id": job_id,
        "state": state.lifecycle_state.value,
    }


@app.post("/workflows/{workflow_id}/execute")
def execute_workflow(workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Start a workflow by ID with an optional initial payload.

    Returns the workflow instance ID that can be used to poll progress.
    """
    from src.gateway.entrypoint import submit_channel_input

    payload.setdefault("_workflow_id", workflow_id)
    result = submit_channel_input(
        _channel_registry, "web", payload, adapter=s5_adapter,
    )
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return {
        "output": result.get("reply", ""),
        "metadata": result.get("metadata", {}),
        "agent_id": result.get("agent_id", ""),
        "reply": result.get("reply", ""),
        "workflow_id": workflow_id,
    }


@app.get("/workflows")
def list_workflows() -> list[dict[str, object]]:
    """List all registered workflow definitions."""
    return [
        {
            "workflow_id": defn.workflow_id,
            "name": defn.name,
            "description": defn.description,
            "steps": list(defn.steps.keys()),
        }
        for defn in wf_registry.list()
    ]


# ── Agent commands ───────────────────────────────────────────────────────


@app.get("/agents")
def list_agents() -> list[dict[str, object]]:
    """List all registered agents with their identity and persona."""
    return [
        {
            "agent_id": meta.identity.agent_id,
            "name": meta.identity.name,
            "description": meta.identity.description,
            "persona": meta.persona,
        }
        for meta in agent_registry.list_agents()
    ]


@app.post("/agents/{agent_id}/chat")
def chat_with_agent(agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Chat with a specific agent by ID.

    The payload should contain an ``input`` or ``message`` field with the
    user's text.
    """
    from src.gateway.entrypoint import submit_channel_input

    text = payload.get("input") or payload.get("message", "")
    result = submit_channel_input(
        _channel_registry, "web", {"input": text},
        adapter=s5_adapter, agent_id=agent_id,
    )
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return {
        "output": result.get("reply", ""),
        "metadata": result.get("metadata", {}),
        "agent_id": result.get("agent_id", agent_id),
        "reply": result.get("reply", ""),
    }


# ── Council commands ─────────────────────────────────────────────────────


@app.get("/councils")
def list_councils() -> list[dict[str, object]]:
    """List all registered council definitions."""
    return [
        {
            "council_id": c.council_id,
            "name": c.name,
            "description": c.description,
            "arbitrator": c.arbitrator_agent_id,
            "members": list(c.member_agent_ids),
        }
        for c in council_registry.list()
    ]


@app.post("/councils/{council_id}/deliberate")
def deliberate_council(council_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Submit a problem to a council for deliberation.

    The payload should contain a ``problem`` or ``question`` field.
    """
    council_def = council_registry.get(council_id)
    if council_def is None:
        raise HTTPException(status_code=404, detail=f"Council '{council_id}' not found")

    problem = payload.get("problem") or payload.get("question", "")

    # Create a minimal calling state (bypass LLM activation cost)
    calling_state = supervisor.create_agent("devsquad-interviewer")
    msg = AgentMessage(message=f"Council deliberation: {problem}")
    calling_state = supervisor.activate_agent(calling_state, msg)
    calling_state = calling_state.with_(lifecycle_state=LifecycleState.RUNNING)

    outcome = council_orchestrator.deliberate(council_def, problem, calling_state)

    return {
        "council_id": outcome.council_id,
        "decision": outcome.decision,
        "confidence": outcome.confidence,
        "member_analyses": outcome.member_analyses,
    }


# ── Session commands ─────────────────────────────────────────────────────


@app.post("/reset")
def reset_session() -> dict[str, str]:
    """Clear the current session and reset agent selection.

    Clears the in-memory conversation history for the default anonymous
    web session so that corrupted state (e.g. orphaned tool_calls that
    causes the haiku fallback) is fully purged without requiring a
    process restart.  The frontend should also clear its local history.
    """
    global _current_agent_id
    _current_agent_id = "default-agent"
    # Clear the server-side session so corrupted history is fully purged.
    s5_adapter.clear_session("web")
    return {"status": "ok", "message": "Session reset — server and frontend history cleared"}


@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check."""
    channel_names = _channel_registry.names
    return {
        "status": "ok",
        "service": "vai-gateway",
        "channels": channel_names,
    }


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
    defs = wf_registry.list()
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
    if wf.steps:
        lines.append("- Steps:")
        for i, (step_id, step) in enumerate(wf.steps.items(), 1):
            label = getattr(step, "label", None) or step_id
            lines.append(f"  {i}. {label}")
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
    print("  VAI - Gateway Transport  (Sprint 13)")
    print("  -----------------------------")
    print(f"  Listening on http://{HOST}:{PORT}")
    print(f"  API docs   http://{HOST}:{PORT}/docs")
    print(f"  Health     http://{HOST}:{PORT}/health")
    print(f"  Chat UI    http://{HOST}:{PORT}/  (PWA)")
    print(f"\n  Channels: {_channel_registry.names}")
    print()
    uvicorn.run("src.platform.transport.app:app", host=HOST, port=PORT, reload=False, log_level="info")


if __name__ == "__main__":
    main()
