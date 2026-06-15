"""
Web Channel Application — FastAPI with Gateway → S5 handoff.

Demonstrates the correct architectural flow::

    HTTP JSON body → Channel.normalize() → submit_channel_input() → S5 Supervisor

Usage::

    python -m tools.channels.web_app

Then::

    curl -X POST http://localhost:8000/api/ingress \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer demo-key-001" \
        -d '{"input": "deploy the app", "sender": "alice", "metadata": {"env": "staging"}}'

    curl http://localhost:8000/health
"""

from __future__ import annotations

import logging
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src.agent.adapters.gateway_adapter import AgentGatewayAdapter
from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
from src.agent.registry import AgentIdentity, AgentMetadata, AgentRegistry
from src.agent.supervisor import Supervisor
from src.gateway.channels.registry import ChannelRegistry
from src.gateway.channels.web import WebChannel, WebRequest, register_web_channel
from src.gateway.entrypoint import submit_channel_input

# ---------------------------------------------------------------------------
# S5 Supervisor wiring
# ---------------------------------------------------------------------------

_agent_registry = AgentRegistry()
_agent_registry.register_agent(AgentMetadata(
    identity=AgentIdentity(
        agent_id="default-agent",
        name="Default Agent",
        description="Default conversational agent",
    ),
    capabilities=["conversation"],
))

_agent_store = MemoryAgentStateStore()
_supervisor = Supervisor(registry=_agent_registry, store=_agent_store)
_s5_adapter = AgentGatewayAdapter(_supervisor)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("web_channel")

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

    result = submit_channel_input(registry, "web", raw, adapter=_s5_adapter)

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
# Root page — professional demo UI
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def root() -> HTMLResponse:
    return HTMLResponse(
        content=_ROOT_PAGE,
        headers={"content-type": "text/html; charset=utf-8"},
    )


_ROOT_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VAI — Web Channel (Gateway → S5)</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #0d1117; color: #e6edf3; line-height: 1.6; padding: 2rem 1rem;
  }
  .container { max-width: 960px; margin: 0 auto; }

  /* Header */
  header { margin-bottom: 2.5rem; }
  header h1 { font-size: 1.75rem; font-weight: 600; letter-spacing: -0.02em; }
  header p { color: #8b949e; font-size: 0.9rem; margin-top: 0.25rem; }
  header .badge {
    display: inline-block; background: #1f6feb; color: #fff;
    font-size: 0.7rem; font-weight: 600; padding: 0.15rem 0.6rem;
    border-radius: 999px; text-transform: uppercase;
  }

  /* Cards */
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; }
  @media (max-width: 720px) { .grid { grid-template-columns: 1fr; } }
  .card {
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 1.25rem 1.5rem;
  }
  .card h2 { font-size: 1rem; font-weight: 600; margin-bottom: 1rem; color: #f0f6fc; }
  .card.full { grid-column: 1 / -1; }

  /* Form elements */
  label { display: block; font-size: 0.8rem; font-weight: 500; color: #8b949e; margin-bottom: 0.3rem; }
  input, textarea {
    width: 100%; padding: 0.5rem 0.75rem; margin-bottom: 0.75rem;
    background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    color: #e6edf3; font-size: 0.875rem; font-family: inherit;
  }
  input:focus, textarea:focus { outline: none; border-color: #1f6feb; box-shadow: 0 0 0 2px rgba(31,111,235,0.3); }
  textarea { font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; font-size: 0.8rem; resize: vertical; min-height: 60px; }
  .row { display: flex; gap: 0.75rem; }
  .row > * { flex: 1; }

  /* Buttons */
  button {
    padding: 0.5rem 1.25rem; border: none; border-radius: 6px;
    font-size: 0.85rem; font-weight: 500; cursor: pointer; transition: background 0.15s;
    background: #238636; color: #fff;
  }
  button:hover { background: #2ea043; }
  button.secondary { background: #21262d; color: #e6edf3; border: 1px solid #30363d; }
  button.secondary:hover { background: #30363d; }
  button:disabled { opacity: 0.5; cursor: default; }

  /* Output */
  .output {
    margin-top: 0.75rem; padding: 0.75rem 1rem;
    background: #0d1117; border: 1px solid #21262d; border-radius: 6px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 0.8rem; white-space: pre-wrap; word-break: break-all;
    max-height: 240px; overflow: auto; display: none;
  }
  .output.visible { display: block; }
  .output.error { border-color: #da3633; color: #ff7b72; }
  .output.success { border-color: #238636; }

  /* Status row */
  .status-row { display: flex; gap: 0.75rem; margin-bottom: 1rem; flex-wrap: wrap; }
  .status-item {
    flex: 1; min-width: 120px; padding: 0.75rem 1rem;
    background: #0d1117; border: 1px solid #21262d; border-radius: 6px; text-align: center;
  }
  .status-item .value { font-size: 1.3rem; font-weight: 600; }
  .status-item .label { font-size: 0.7rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.04em; }
  .status-item.up .value { color: #3fb950; }
  .status-item.down .value { color: #da3633; }

  /* Navigation */
  .nav-links { margin-top: 2rem; text-align: center; font-size: 0.85rem; }
  .nav-links a { color: #58a6ff; text-decoration: none; }
  .nav-links a:hover { text-decoration: underline; }
  .nav-links .sep { color: #30363d; margin: 0 0.5rem; }
</style>
</head>
<body>
<div class="container">

  <header>
    <h1>VAI · Web Channel (Gateway → S5)</h1>
    <p>Interact with the Gateway → S5 Supervisor handoff &nbsp;<span class="badge">demo</span></p>
  </header>

  <!-- Status bar -->
  <div class="status-row" id="statusBar">
    <div class="status-item" id="healthIndicator"><div class="value">…</div><div class="label">Service</div></div>
    <div class="status-item"><div class="value" id="channelCount">—</div><div class="label">Registered Channels</div></div>
  </div>

  <!-- Tool grid -->
  <div class="grid">

    <!-- Ingress card -->
    <div class="card">
        <h2>⬇  Ingress — Submit to S5</h2>
      <p style="font-size:0.8rem;color:#8b949e;margin-bottom:1rem;">
          HTTP JSON → ChannelMessage → S5 Supervisor
      </p>
      <label for="ingressInput">Input text</label>
      <input type="text" id="ingressInput" placeholder="e.g. deploy the app" value="deploy the app">
      <div class="row">
        <div>
          <label for="ingressSender">Sender (optional)</label>
          <input type="text" id="ingressSender" placeholder="alice" value="alice">
        </div>
        <div>
          <label for="ingressAuth">Authorization</label>
          <input type="text" id="ingressAuth" placeholder="Bearer …" value="Bearer demo-key-001">
        </div>
      </div>
        <button id="ingressBtn">Submit to S5</button>
      <div class="output" id="ingressOutput"></div>
    </div>

      <!-- Inspect card -->
      <div class="card full">
        <h2>🔍  Registered Channels</h2>
        <p style="font-size:0.8rem;color:#8b949e;margin-bottom:1rem;">
          Query <code>GET /api/inspect</code> to see what channels are wired.
        </p>
        <button id="inspectBtn" class="secondary">Refresh</button>
        <div class="output" id="inspectOutput"></div>
      </div>

  </div>

  <div class="nav-links">
    <a href="/docs">OpenAPI Docs</a>
    <span class="sep">·</span>
    <a href="/health">Health (JSON)</a>
    <span class="sep">·</span>
    <a href="/api/inspect">Inspect (JSON)</a>
  </div>

</div>

<script>
const BASE = '';

async function api(url, method, body, auth) {
  const hdrs = { 'Content-Type': 'application/json' };
  if (auth) hdrs['Authorization'] = auth;
  const res = await fetch(BASE + url, { method, headers: hdrs, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json();
  return { ok: res.ok, status: res.status, data };
}

function show(el, data, ok) {
  el.textContent = JSON.stringify(data, null, 2);
  el.className = 'output visible' + (ok ? ' success' : ' error');
}

// --- Ingress ---
document.getElementById('ingressBtn').addEventListener('click', async () => {
  const btn = document.getElementById('ingressBtn'); btn.disabled = true;
  try {
    const input = document.getElementById('ingressInput').value;
    const sender = document.getElementById('ingressSender').value || undefined;
    const auth = document.getElementById('ingressAuth').value || undefined;
    const body = { input };
    if (sender) body.sender = sender;
    const { ok, data } = await api('/api/ingress', 'POST', body, auth);
    show(document.getElementById('ingressOutput'), data, ok);
  } finally { btn.disabled = false; }
});

// --- Inspect ---
document.getElementById('inspectBtn').addEventListener('click', async () => {
  const btn = document.getElementById('inspectBtn'); btn.disabled = true;
  try {
    const { ok, data } = await api('/api/inspect', 'GET');
    show(document.getElementById('inspectOutput'), data, ok);
  } finally { btn.disabled = false; }
});

// --- Startup health check ---
(async function init() {
  try {
    const { ok, data } = await api('/health', 'GET');
    const ind = document.getElementById('healthIndicator');
    ind.className = 'status-item' + (ok ? ' up' : ' down');
    ind.querySelector('.value').textContent = ok ? 'Up' : 'Down';
    document.getElementById('channelCount').textContent =
      (data.channels && data.channels.length) || 0;
    // auto-show inspect
    const { ok: iok, data: idata } = await api('/api/inspect', 'GET');
    show(document.getElementById('inspectOutput'), idata, iok);
  } catch (e) {
    const ind = document.getElementById('healthIndicator');
    ind.className = 'status-item down';
    ind.querySelector('.value').textContent = 'Error';
  }
})();
</script>

</body>
</html>
"""


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

HOST = "127.0.0.1"
PORT = 8000


def main() -> None:
    print(f"  VAI — Web Channel (Gateway → S5)  v0.2.0")
    print(f"  ──────────────────────────────────────────")
    print(f"  Listening on http://{HOST}:{PORT}")
    print(f"  API docs   http://{HOST}:{PORT}/docs")
    print(f"  Health     http://{HOST}:{PORT}/health")
    print(f"  Ingress    POST /api/ingress  (WebRequest JSON body)")
    print(f"  Egress     POST /api/egress   (outbound payload)")
    print(f"  Inspect    GET  /api/inspect")
    print(f"\n  Channels: {registry.names}")
    print()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
