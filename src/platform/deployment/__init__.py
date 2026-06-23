"""S4.9.2 — Deployment Targets for Stratum-4.

Defines how S4 is packaged and executed across supported environments:
local (developer machine) and container (Docker/OCI).
Cloud deployment is acknowledged but intentionally deferred.
"""

from __future__ import annotations

import signal
import sys
from typing import Optional

from src.config import S4Config, load_config
from src.platform.runtime.worker_entrypoint import run_worker_pool


class DeploymentError(Exception):
    """Raised when deployment setup or execution fails."""


# ---------------------------------------------------------------------------
# Common bootstrap
# ---------------------------------------------------------------------------


def _load_s4_config(config_file: Optional[str] = None) -> S4Config:
    """Load S4 configuration from defaults, file, env vars, and overrides.

    Args:
        config_file: Optional path to a YAML config file.

    Returns:
        An immutable ``S4Config`` instance.
    """
    return load_config(config_file=config_file)


# ---------------------------------------------------------------------------
# Local deployment
# ---------------------------------------------------------------------------


def _run_local(config: Optional[S4Config] = None) -> None:
    """Run S4 locally as a bare Python process.

    Starts the worker pool with the concurrency configured in *config*.
    Uses the local filesystem for logs, metrics, and checkpoints.
    Zero external dependencies required.
    """
    if config is None:
        config = _load_s4_config()

    worker_count = config.get("workers.count")
    _info(f"Starting S4 worker pool (local mode, {worker_count} workers)")

    try:
        run_worker_pool()
    except KeyboardInterrupt:
        _info("Received SIGINT, shutting down S4")
    finally:
        _info("S4 stopped")


# ---------------------------------------------------------------------------
# Container deployment
# ---------------------------------------------------------------------------


def _run_container(config: Optional[S4Config] = None) -> None:
    """Run S4 inside a containerised environment.

    S4 runs as PID 1.  Logging goes to stdout/stderr.  Configuration is
    driven entirely by environment variables (see S4.9.1 Config System).
    Graceful shutdown is handled via SIGTERM.

    This function is the Python-side entrypoint.  The container image
    entrypoint should call ``run_target("container")``.
    """
    if config is None:
        config = _load_s4_config()

    # Register SIGTERM handler for container-safe graceful shutdown
    def _handle_sigterm(signum: int, frame: object) -> None:
        _info("Received SIGTERM, shutting down S4 daemon")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    worker_count = config.get("workers.count")
    _info(f"Starting S4 daemon (container mode, {worker_count} workers)")

    try:
        run_worker_pool()
    except KeyboardInterrupt:
        _info("Received SIGINT, shutting down S4 daemon")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_application() -> dict:
    """Create the wired application composition root.

    Instantiates and wires all strata layers, returning a dict of
    components ready for use.  This is the single entrypoint for
    programmatic embedding (tests, CLI, FastAPI).

    Returns:
        A dict with keys ``queue``, ``job_store``, ``strategy_router``,
        ``supervisor``, ``registry``, ``state_store``.
    """
    from src.platform.queue import InMemoryQueue
    from src.platform.runtime.job_store import InMemoryJobStore

    from src.agent.registry import AgentRegistry
    from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
    from src.agent.strategy_router import StrategyRouter
    from src.agent.supervisor import Supervisor

    # S4: generic durable execution
    queue = InMemoryQueue()
    job_store = InMemoryJobStore()

    # S5: agent orchestration
    registry = AgentRegistry()
    state_store = MemoryAgentStateStore()
    strategy_router = StrategyRouter()
    supervisor = Supervisor(
        registry=registry,
        store=state_store,
        strategy_router=strategy_router,
    )

    return {
        "queue": queue,
        "job_store": job_store,
        "strategy_router": strategy_router,
        "supervisor": supervisor,
        "registry": registry,
        "state_store": state_store,
    }


def run_target(mode: str = "local") -> None:
    """Run S4 in the given deployment mode.

    This is the single entrypoint for all supported deployment targets.

    Args:
        mode: One of ``"local"`` or ``"container"``.

    Raises:
        DeploymentError: If *mode* is not recognised.
    """
    config = _load_s4_config()

    if mode == "local":
        _run_local(config)
    elif mode == "container":
        _run_container(config)
    else:
        raise DeploymentError(f"Unknown deployment mode: {mode!r}")


def _info(msg: str) -> None:
    """Emit a deployment bootstrap message (stdout for container‑safety)."""
    print(f"[deployment] {msg}", file=sys.stderr, flush=True)
