"""
VAI Web Channel — thin wrapper around ``src.platform.transport.app``.

Usage::

    python -m tools.channels.web_app

All routes (``/run``, ``/health``, ``/agents``, ``/workflows``, ``/councils``,
``/reset``, etc.) are served by the production transport gateway.

This module exists only as a convenience entry point for development and
will be deprecated in a future release.  Please use::

    python -m src.platform.transport.app
"""

import uvicorn

from src.platform.transport.app import _channel_registry, app

HOST = "0.0.0.0"
PORT = 8000


def main() -> None:
    """Start the transport gateway on the default port."""
    print("  VAI - Web Channel PWA  (DEPRECATED — use src.platform.transport.app)")
    print("  ----------------------------------------------------------------")
    print(f"  Listening on http://{HOST}:{PORT}")
    print(f"  API docs   http://{HOST}:{PORT}/docs")
    print(f"  Health     http://{HOST}:{PORT}/health")
    print(f"  Chat UI    http://{HOST}:{PORT}/  (PWA)")
    print(f"\n  Channels: {_channel_registry.names}")
    print()
    uvicorn.run("tools.channels.web_app:app", host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()

