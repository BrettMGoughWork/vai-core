"""
MCPClientManager — manages MCP server subprocesses and exposes a
synchronous ``get_server()`` / ``call_tool()`` interface.

Each MCP server runs in a background daemon thread with its own asyncio
event loop.  Calls are dispatched via ``run_coroutine_threadsafe`` and
block the caller until the result is ready (or a timeout fires).

Usage::

    manager = MCPClientManager("config/mcp_servers.yaml")
    server = manager.get_server("google-workspace-mcp")
    if server:
        result = server.call_tool("drive.search", {"query": "..."})
    manager.shutdown()
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Command resolution
# ---------------------------------------------------------------------------

# Common directories (Windows) to search when ``shutil.which()`` fails
_COMMON_BIN_DIRS: list[str] = [
    r"C:\Program Files\nodejs",
    r"C:\Program Files (x86)\nodejs",
    os.path.expandvars(r"%APPDATA%\npm"),
    os.path.expandvars(r"%LOCALAPPDATA%\fnm\aliases\default\bin"),
]
# Extensions that need ``cmd.exe /c`` wrapping on Windows
_CMD_WRAP_EXTENSIONS = {".cmd", ".bat"}


def _resolve_command(
    command: str, args: list[str]
) -> tuple[str, list[str], dict[str, str] | None] | None:
    """Resolve *command* to an absolute path, wrapping in ``cmd.exe /c``
    when the target is a ``.cmd`` / ``.bat`` script.

    Returns ``(command, args, extra_env)`` or ``None`` if not found.
    The *extra_env* dict contains PATH entries that must be added to the
    subprocess environment so that the command's runtime dependencies
    (e.g. ``node`` for ``npx.cmd``) are also found.
    """
    extra_env: dict[str, str] = {}
    resolved = shutil.which(command)
    if not resolved:
        # Fallback: search common install directories
        for d in _COMMON_BIN_DIRS:
            for candidate in _iter_candidates(d, command):
                if os.path.isfile(candidate):
                    resolved = candidate
                    break
            if resolved:
                break
    if not resolved:
        return None

    # When the command lives inside a directory like ``C:\Program Files\nodejs``,
    # add that directory to PATH so runtime dependencies (e.g. ``node`` for
    # ``npx.cmd``) are also found by the subprocess.
    cmd_dir = os.path.dirname(os.path.abspath(resolved))
    if cmd_dir not in os.environ.get("PATH", "").split(os.pathsep):
        extra_env["PATH"] = cmd_dir + os.pathsep + os.environ.get("PATH", "")

    if os.path.splitext(resolved)[1].lower() in _CMD_WRAP_EXTENSIONS:
        # ``.cmd`` / ``.bat`` files cannot be spawned directly via
        # ``subprocess.Popen(shell=False)`` on Windows — wrap with
        # ``cmd.exe /c``.
        return ("cmd.exe", ["/c", resolved, *args], extra_env)

    return (resolved, args, extra_env if extra_env else None)


def _iter_candidates(directory: str, command: str):
    """Yield possible paths for *command* inside *directory*."""
    base = os.path.join(directory, command)
    yield base  # exact match (e.g. ``npx`` → ``nodejs\npx``)
    for ext in (".cmd", ".exe", ".bat", ".com"):
        yield base + ext


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path("config/mcp_servers.yaml")
_CALL_TIMEOUT = 120.0  # seconds per tool call
_CONNECT_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MCPClientError(Exception):
    """Base for MCP client errors."""


class ServerNotFound(MCPClientError):
    """Requested server name is not configured."""


class ServerConnectionFailed(MCPClientError):
    """Could not connect to or initialize the MCP server."""


class ToolCallFailed(MCPClientError):
    """The MCP server returned an error for the requested tool."""


# ---------------------------------------------------------------------------
# Server configuration
# ---------------------------------------------------------------------------


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server process."""

    name: str
    """Unique identifier for this server (e.g. ``'google-workspace-mcp'``)."""

    command: str
    """Executable to run (e.g. ``'npx'``, ``'uvx'``, ``'python'``)."""

    args: list[str] = field(default_factory=list)
    """Arguments passed to *command*."""

    env: dict[str, str] = field(default_factory=dict)
    """Extra environment variables injected into the server process."""

    cwd: str | None = None
    """Working directory for the server process (optional)."""

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> MCPServerConfig:
        """Build from a parsed YAML dict."""
        env = dict(data.get("env", {}))
        # Resolve ``${VAR}`` / ``$VAR`` placeholders from the OS environment
        for key, val in env.items():
            env[key] = os.path.expandvars(val)

        command = data["command"]
        args = list(data.get("args", []))
        # Resolve ``npx``, ``uvx`` etc. to a full path so the subprocess
        # finds them even when PATH varies between shells.
        resolved = _resolve_command(command, args)
        if resolved is not None:
            command, args, extra_env = resolved
            # Merge extra PATH entries into env so that runtime dependencies
            # (e.g. ``node`` for ``npx.cmd``) are found by the subprocess.
            if extra_env:
                for key, val in extra_env.items():
                    existing = env.get(key)
                    if existing:
                        env[key] = val + os.pathsep + existing
                    else:
                        env[key] = val

        return cls(
            name=name,
            command=command,
            args=args,
            env=env,
            cwd=data.get("cwd"),
        )

    def to_stdlib_params(self) -> StdioServerParameters:
        """Convert to the ``mcp`` library's ``StdioServerParameters``."""
        return StdioServerParameters(
            command=self.command,
            args=list(self.args),
            env=dict(self.env) if self.env else None,
            cwd=self.cwd,
        )


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def load_server_configs(path: str | Path = _DEFAULT_CONFIG_PATH) -> dict[str, MCPServerConfig]:
    """Load MCP server configurations from a YAML file.

    Expected format::

        servers:
          google-workspace-mcp:
            command: npx
            args: ["-y", "@dguido/google-workspace-mcp"]
            env:
              GOOGLE_CLIENT_ID: "${GOOGLE_CLIENT_ID}"
              GOOGLE_CLIENT_SECRET: "${GOOGLE_CLIENT_SECRET}"
              GOOGLE_WORKSPACE_SERVICES: "${GOOGLE_WORKSPACE_SERVICES}"
    """
    path = Path(path)
    if not path.exists():
        logger.info("MCP server config not found at %s — no MCP servers configured", path)
        return {}

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        return {}

    servers_raw = raw.get("servers", {})
    if not isinstance(servers_raw, dict):
        return {}

    configs: dict[str, MCPServerConfig] = {}
    for name, data in servers_raw.items():
        if not isinstance(data, dict) or "command" not in data:
            logger.warning("Skipping MCP server %r: missing 'command'", name)
            continue
        try:
            configs[name] = MCPServerConfig.from_dict(name, data)
        except Exception as exc:
            logger.warning("Skipping MCP server %r: %s", name, exc)
    return configs


# ---------------------------------------------------------------------------
# Server handle (synchronous wrapper around an async MCP session)
# ---------------------------------------------------------------------------


class _MCPServerHandle:
    """Synchronous handle for calling tools on a connected MCP server.

    Owns a background daemon thread that runs the asyncio event loop and
    maintains the ``ClientSession`` connection to the MCP server process.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: ClientSession | None = None
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._lock = threading.Lock()

        self._start()

    # ------------------------------------------------------------------
    # Lifecycle (internal)
    # ------------------------------------------------------------------

    def _start(self) -> None:
        """Launch the background thread and wait for the session to connect."""
        self._loop = asyncio.new_event_loop()
        self._shutdown_event = asyncio.Event()
        self._thread = threading.Thread(
            target=self._run_event_loop,
            name=f"mcp-{self._config.name}",
            daemon=True,
        )
        self._thread.start()

        if not self._ready.wait(timeout=_CONNECT_TIMEOUT):
            self._loop.call_soon_threadsafe(self._loop.stop)
            raise ServerConnectionFailed(
                f"MCP server {self._config.name!r} did not connect "
                f"within {_CONNECT_TIMEOUT}s"
            )

        # Re-raise any connection error caught in the background thread
        if self._error is not None:
            raise ServerConnectionFailed(
                f"MCP server {self._config.name!r} failed: {self._error}"
            ) from self._error

    def _run_event_loop(self) -> None:
        """Target for the background thread — runs the asyncio event loop."""
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_session())
        except Exception:
            logger.exception(
                "MCP server %r event loop exited with error", self._config.name
            )
        finally:
            self._loop.close()

    async def _run_session(self) -> None:
        """Connect to the MCP server and keep the session alive."""
        params = self._config.to_stdlib_params()
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    caps = session.get_server_capabilities()
                    logger.info(
                        "MCP server %r connected. Capabilities: %s",
                        self._config.name,
                        caps,
                    )
                    self._session = session
                    self._ready.set()

                    # Keep the event loop alive until shutdown is signalled
                    await self._shutdown_event.wait()
        except Exception as exc:
            self._error = exc
            self._ready.set()  # unblock caller
            logger.error(
                "MCP server %r connection failed: %s", self._config.name, exc
            )

    def _check_session(self) -> None:
        """Raise if the session is not connected."""
        if self._session is None:
            raise ServerConnectionFailed(
                f"MCP server {self._config.name!r} session is not connected"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool on the MCP server synchronously.

        Args:
            name: Tool name as exposed by the MCP server.
            arguments: Tool arguments dict (JSON-serialisable).

        Returns:
            The tool result content (decoded from ``CallToolResult``).

        Raises:
            ServerConnectionFailed: If the session is not connected.
            ToolCallFailed: If the server returns an error or the call times out.
        """
        self._check_session()
        assert self._session is not None
        assert self._loop is not None

        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(name, arguments),
            self._loop,
        )

        try:
            result: CallToolResult = future.result(timeout=_CALL_TIMEOUT)
        except asyncio.TimeoutError:
            raise ToolCallFailed(
                f"Tool {name!r} on server {self._config.name!r} "
                f"timed out after {_CALL_TIMEOUT}s"
            ) from None

        if result.isError:
            error_msg = _extract_error(result)
            raise ToolCallFailed(
                f"Tool {name!r} on server {self._config.name!r} "
                f"failed: {error_msg}"
            )

        return _extract_content(result)

    def stop(self) -> None:
        """Signal the background thread to shut down gracefully."""
        if self._shutdown_event and self._loop and not self._shutdown_event.is_set():
            self._loop.call_soon_threadsafe(self._shutdown_event.set)


def _extract_content(result: CallToolResult) -> Any:
    """Extract human-readable content from a ``CallToolResult``."""
    if not result.content:
        return ""
    parts: list[str] = []
    for item in result.content:
        if hasattr(item, "text") and item.text:
            parts.append(item.text)
        elif hasattr(item, "data") and item.data:
            parts.append(str(item.data))
    return "\n".join(parts) if len(parts) > 1 else (parts[0] if parts else "")


def _extract_error(result: CallToolResult) -> str:
    """Extract error message from a failed ``CallToolResult``."""
    if result.content:
        texts = [
            getattr(c, "text", str(c))
            for c in result.content
            if hasattr(c, "text")
        ]
        return "; ".join(texts)
    return "unknown error"


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class MCPClientManager:
    """Manages MCP server processes, providing a ``get_server()`` interface.

    Servers are configured in a YAML file (default ``config/mcp_servers.yaml``).
    They are connected lazily — the first call to ``get_server()`` spawns the
    process and establishes the session.
    """

    def __init__(self, config_path: str | Path = _DEFAULT_CONFIG_PATH) -> None:
        self._configs = load_server_configs(config_path)
        self._handles: dict[str, _MCPServerHandle] = {}
        self._lock = threading.Lock()

    def get_server(self, name: str) -> _MCPServerHandle | None:
        """Return a handle for the named server, or ``None`` if unknown.

        The server process is spawned and connected on first access (lazy).
        """
        if name not in self._configs:
            return None

        with self._lock:
            if name not in self._handles:
                self._handles[name] = _MCPServerHandle(self._configs[name])
            return self._handles[name]

    def list_servers(self) -> list[str]:
        """Return the names of all configured MCP servers."""
        return list(self._configs.keys())

    def is_started(self, name: str) -> bool:
        """Return ``True`` if the server *name* has been started."""
        return name in self._handles

    def shutdown(self) -> None:
        """Gracefully stop all connected MCP servers."""
        for name, handle in list(self._handles.items()):
            try:
                handle.stop()
            except Exception:
                logger.exception("Error stopping MCP server %r", name)
        self._handles.clear()


__all__ = [
    "MCPClientManager",
    "MCPServerConfig",
    "MCPClientError",
    "ServerNotFound",
    "ServerConnectionFailed",
    "ToolCallFailed",
    "load_server_configs",
]
