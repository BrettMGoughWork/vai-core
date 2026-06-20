"""Tests for MCPClientManager, MCPServerConfig, and load_server_configs."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from src.capabilities.primitives.mcp_client import (
    MCPClientManager,
    MCPServerConfig,
    ServerConnectionFailed,
    ToolCallFailed,
    load_server_configs,
)


# ---------------------------------------------------------------------------
# MCPServerConfig
# ---------------------------------------------------------------------------


class TestMCPServerConfig:
    def test_from_dict_minimal(self) -> None:
        config = MCPServerConfig.from_dict("my-server", {"command": "npx", "args": ["-y", "some-pkg"]})
        assert config.name == "my-server"
        # Command may be resolved to a full path on systems where npx is installed
        name_no_ext = os.path.splitext(os.path.basename(config.command))[0]
        assert name_no_ext == "npx", f"Expected npx, got {name_no_ext}"
        assert config.args == ["-y", "some-pkg"]
        # When the command lives in a directory not on PATH (e.g. npx in
        # C:\Program Files\nodejs), the resolver injects PATH into env so
        # runtime deps like ``node`` are found by the subprocess.
        if "PATH" not in config.env:
            assert config.env == {}
        assert config.cwd is None

    def test_from_dict_with_env(self) -> None:
        config = MCPServerConfig.from_dict(
            "srv",
            {
                "command": "uvx",
                "args": ["tool"],
                "env": {"TOKEN": "abc", "MODE": "prod"},
                "cwd": "/opt/server",
            },
        )
        assert config.env == {"TOKEN": "abc", "MODE": "prod"}
        assert config.cwd == "/opt/server"

    def test_from_dict_expands_env_vars(self) -> None:
        os.environ["_TEST_MCP_KEY"] = "secret-value"
        try:
            config = MCPServerConfig.from_dict(
                "srv",
                {"command": "npx", "env": {"API_KEY": "${_TEST_MCP_KEY}"}},
            )
            assert config.env["API_KEY"] == "secret-value"
        finally:
            os.environ.pop("_TEST_MCP_KEY", None)

    def test_to_stdlib_params(self) -> None:
        config = MCPServerConfig(
            name="test",
            command="npx",
            args=["-y", "pkg"],
            env={"VAR": "val"},
            cwd="/tmp",
        )
        params = config.to_stdlib_params()
        assert params.command == "npx"
        assert params.args == ["-y", "pkg"]
        assert params.env == {"VAR": "val"}
        assert params.cwd == "/tmp"


# ---------------------------------------------------------------------------
# load_server_configs
# ---------------------------------------------------------------------------


class TestLoadServerConfigs:
    def test_missing_file_returns_empty(self) -> None:
        configs = load_server_configs("nonexistent_file.yaml")
        assert configs == {}

    def test_empty_file_returns_empty(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("")
            tmp = fh.name
        try:
            configs = load_server_configs(tmp)
            assert configs == {}
        finally:
            os.unlink(tmp)

    def test_valid_config(self) -> None:
        data = {
            "servers": {
                "alpha": {"command": "npx", "args": ["-y", "alpha-pkg"]},
                "beta": {
                    "command": "uvx",
                    "args": ["beta-tool"],
                    "env": {"SECRET": "s3cr3t"},
                    "cwd": "/data",
                },
            }
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as fh:
            yaml.dump(data, fh)
            tmp = fh.name
        try:
            configs = load_server_configs(tmp)
            assert set(configs) == {"alpha", "beta"}
            name_no_ext = os.path.splitext(os.path.basename(configs["alpha"].command))[0]
            assert name_no_ext == "npx", f"Expected npx, got {name_no_ext}"
            name_no_ext = os.path.splitext(os.path.basename(configs["beta"].command))[0]
            assert name_no_ext == "uvx", f"Expected uvx, got {name_no_ext}"
            assert configs["beta"].env == {"SECRET": "s3cr3t"}
        finally:
            os.unlink(tmp)

    def test_skips_server_without_command(self) -> None:
        data = {"servers": {"bad": {"args": ["-y", "x"]}}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as fh:
            yaml.dump(data, fh)
            tmp = fh.name
        try:
            configs = load_server_configs(tmp)
            assert configs == {}
        finally:
            os.unlink(tmp)

    def test_ignores_non_dict_servers(self) -> None:
        data = {"servers": "not a dict"}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as fh:
            yaml.dump(data, fh)
            tmp = fh.name
        try:
            configs = load_server_configs(tmp)
            assert configs == {}
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# MCPClientManager
# ---------------------------------------------------------------------------


class TestMCPClientManager:
    def test_empty_config(self, tmp_path: Path) -> None:
        """Manager with no servers."""
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("", encoding="utf-8")
        manager = MCPClientManager(str(config_path))

        assert manager.list_servers() == []
        assert manager.get_server("nonexistent") is None
        assert manager.is_started("nonexistent") is False

    def test_list_servers(self, tmp_path: Path) -> None:
        """list_servers() returns configured server names."""
        config_path = tmp_path / "servers.yaml"
        config_path.write_text(
            yaml.dump({
                "servers": {
                    "a": {"command": "x"},
                    "b": {"command": "y"},
                }
            }),
            encoding="utf-8",
        )
        manager = MCPClientManager(str(config_path))
        assert sorted(manager.list_servers()) == ["a", "b"]

    def test_shutdown_no_servers(self, tmp_path: Path) -> None:
        """shutdown() on an idle manager is a no-op."""
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("", encoding="utf-8")
        manager = MCPClientManager(str(config_path))
        manager.shutdown()  # should not raise


# ---------------------------------------------------------------------------
# _MCPServerHandle connection failure
# ---------------------------------------------------------------------------


class TestMCPServerHandleFailure:
    def test_missing_executable_raises(self) -> None:
        """If the server executable doesn't exist, ServerConnectionFailed is raised."""
        with patch("src.capabilities.primitives.mcp_client._CONNECT_TIMEOUT", 3):
            config = MCPServerConfig(
                name="fail-server", command="nonexistent-cmd-xyz-98765"
            )
            with pytest.raises(ServerConnectionFailed):
                from src.capabilities.primitives.mcp_client import _MCPServerHandle

                _MCPServerHandle(config)


# ---------------------------------------------------------------------------
# parse / error helpers (private — tested indirectly via MCPPrimitive)
# ---------------------------------------------------------------------------


def test_extract_content_text() -> None:
    from mcp.types import CallToolResult, TextContent

    result = CallToolResult(content=[TextContent(type="text", text="hello world")], isError=False)
    from src.capabilities.primitives.mcp_client import _extract_content

    assert _extract_content(result) == "hello world"


def test_extract_content_multiple() -> None:
    from mcp.types import CallToolResult, TextContent

    result = CallToolResult(
        content=[
            TextContent(type="text", text="part a"),
            TextContent(type="text", text="part b"),
        ],
        isError=False,
    )
    from src.capabilities.primitives.mcp_client import _extract_content

    assert _extract_content(result) == "part a\npart b"


def test_extract_content_empty() -> None:
    from mcp.types import CallToolResult

    result = CallToolResult(content=[], isError=False)
    from src.capabilities.primitives.mcp_client import _extract_content

    assert _extract_content(result) == ""


def test_extract_error() -> None:
    from mcp.types import CallToolResult, TextContent

    result = CallToolResult(
        content=[TextContent(type="text", text="something went wrong")],
        isError=True,
    )
    from src.capabilities.primitives.mcp_client import _extract_error

    assert _extract_error(result) == "something went wrong"


def test_extract_error_unknown() -> None:
    from mcp.types import CallToolResult

    result = CallToolResult(content=[], isError=True)
    from src.capabilities.primitives.mcp_client import _extract_error

    assert _extract_error(result) == "unknown error"
