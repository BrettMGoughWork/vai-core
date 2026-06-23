"""Web Simple Channel — pure-logic adapter + PWA UI frontend.

This package contains both the web channel adapter (pure logic, no IO) and
a vanilla-JS Progressive Web App frontend served by the gateway's FastAPI app.

Mount into a gateway app with::

    from src.gateway.channels.web_simple import mount_ui
    mount_ui(app)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.gateway.channels.web_simple.adapter import (
    WebChannel,
    WebRequest,
    WebResponse,
    register_web_channel,
)

if TYPE_CHECKING:
    pass

__all__ = [
    "WebChannel",
    "WebRequest",
    "WebResponse",
    "register_web_channel",
    "mount_ui",
]

# Resolve the UI directory relative to this __init__.py
_UI_DIR = Path(__file__).resolve().parent / "ui"


def mount_ui(app: FastAPI, *, ui_dir: str | Path | None = None) -> None:
    """Mount the web_simple PWA frontend into a FastAPI *app*.

    This adds:
    - ``GET /`` → serves the chat UI shell (``index.html``)
    - ``GET /static/*`` → serves static assets (JS, CSS, icons, manifest)

    The existing ``POST /run`` and ``GET /jobs/{job_id}`` routes are
    left untouched — the gateway must register those separately.

    Args:
        app: The FastAPI application to mount into.
        ui_dir: Optional override path to the UI directory. Defaults to
                the ``ui/`` directory alongside this module.
    """
    ui_path = Path(ui_dir) if ui_dir else _UI_DIR

    static_dir = ui_path / "static"
    if static_dir.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(static_dir)),
            name="web_simple_static",
        )

    # Serve the chat UI shell at /
    app.add_api_route(
        "/",
        lambda: FileResponse(str(ui_path / "index.html")),
        methods=["GET"],
        include_in_schema=False,
    )
