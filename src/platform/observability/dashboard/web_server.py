"""
Dashboard Web Server — lightweight HTTP/SSE frontend for the S4 Dashboard.

Implements:
- Static file serving of ``index.html`` from an embedded ``static/`` directory.
- ``GET /api/state`` — full JSON state snapshot.
- ``GET /api/events/stream`` — SSE for live-updates.
- ``GET /api/events/recent?n=50`` — recent raw events.
- ``GET /api/summary`` — condensed dashboard summary.

All routes are read-only.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from collections.abc import Callable
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

from src.platform.observability.dashboard.event_model import DashboardEventStore

HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"


class DashboardHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for the S4 Dashboard API and static files."""

    # Class-level references set by the factory
    store: DashboardEventStore | None = None
    sse_clients: list[queue.Queue] = []
    sse_lock: threading.Lock = threading.Lock()

    # Silence default HTTP server logs
    def log_message(self, fmt: str, *args: Any) -> None:
        return  # we provide our own logging via stderr

    def do_GET(self) -> None:
        """Route GET requests."""
        path = self.path

        if path == "/api/state":
            self._send_json(self.store.get_state_dict())
        elif path == "/api/summary":
            self._send_json(self.store.get_summary())
        elif path == "/api/events/stream":
            self._handle_sse()
        elif path.startswith("/api/events/recent"):
            self._handle_recent_events()
        elif path in ("/", "/index.html"):
            self._serve_static("index.html")
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/"):])
        else:
            # Try serving the file from static dir
            self._serve_static(path.lstrip("/"))
        return  # type: ignore[return-value]

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        """Send a JSON response."""
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, filename: str) -> None:
        """Serve a file from the static directory."""
        # Prevent directory traversal
        safe_name = Path(filename).name
        filepath = STATIC_DIR / safe_name

        if not filepath.exists() or not filepath.is_file():
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        # Determine content type
        ext = filepath.suffix.lower()
        content_types = {
            ".html": "text/html",
            ".js": "application/javascript",
            ".css": "text/css",
            ".json": "application/json",
            ".png": "image/png",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }
        content_type = content_types.get(ext, "application/octet-stream")

        try:
            body = filepath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except OSError as exc:
            print(f"[dashboard] Error serving {filename}: {exc}", file=sys.stderr)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal Server Error")

    def _handle_sse(self) -> None:
        """Handle Server-Sent Events streaming."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        client_queue: queue.Queue = queue.Queue(maxsize=200)

        with self.__class__.sse_lock:
            self.__class__.sse_clients.append(client_queue)

        try:
            # Send initial state
            initial = self.store.get_state_dict()
            msg = f"data: {json.dumps({'type': 'full_state', 'payload': initial}, default=str)}\n\n"
            self.wfile.write(msg.encode("utf-8"))
            self.wfile.flush()

            # Stream events
            while True:
                try:
                    data = client_queue.get(timeout=15)
                    if data is None:  # shutdown signal
                        break

                    event = data.get("event", "")
                    payload = data
                    sse_body = json.dumps(
                        {"type": "event", "event_type": event, "payload": payload},
                        default=str,
                    )
                    msg = f"data: {sse_body}\n\n"
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # Send keepalive
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()

        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with self.__class__.sse_lock:
                if client_queue in self.__class__.sse_clients:
                    self.__class__.sse_clients.remove(client_queue)

    def _handle_recent_events(self) -> None:
        """Return recent raw events as JSON."""
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        try:
            n = int(qs.get("n", ["50"])[0])
        except (ValueError, IndexError):
            n = 50
        n = max(1, min(n, 500))

        events = self.store.get_recent_events(n)
        self._send_json({"events": events, "count": len(events)})


def make_handler(store: DashboardEventStore) -> type[SimpleHTTPRequestHandler]:
    """Create a handler class wired to a specific event store instance."""
    # Fresh SSE client list per handler class
    cls = type(
        "DashboardHandler",
        (DashboardHTTPHandler,),
        {
            "store": store,
            "sse_clients": [],
            "sse_lock": threading.Lock(),
        },
    )
    return cls


def _sse_broadcast(
    store: DashboardEventStore, handler_cls: type[SimpleHTTPRequestHandler]
) -> None:
    """Background thread that pushes events from the store to SSE clients."""

    def _push_to_clients(data: dict[str, Any]) -> None:
        with handler_cls.sse_lock:  # type: ignore[attr-defined]
            clients = list(handler_cls.sse_clients)  # type: ignore[attr-defined]
        for client_queue in clients:
            try:
                client_queue.put_nowait(data)
            except queue.Full:
                pass

    store.subscribe(_push_to_clients)


class DashboardWebServer:
    """Lightweight web server for the S4 Observability Dashboard.

    Serves the static frontend and a REST/SSE API from a single process.
    """

    def __init__(
        self,
        store: DashboardEventStore,
        host: str = "localhost",
        port: int = 8765,
    ) -> None:
        self.store = store
        self.host = host
        self.port = port
        self._handler_cls = make_handler(store)

    def serve_forever(self) -> None:
        """Start the HTTP server (blocks until KeyboardInterrupt)."""
        _sse_broadcast(self.store, self._handler_cls)

        server = HTTPServer((self.host, self.port), self._handler_cls)
        server.timeout = 0.5  # Allow KeyboardInterrupt to be caught

        print(
            f"[dashboard] API at http://{self.host}:{self.port}/api/state",
            file=sys.stderr,
        )

        try:
            while True:
                server.handle_request()
        except KeyboardInterrupt:
            print("\n[dashboard] Server stopped.", file=sys.stderr)
            server.server_close()
