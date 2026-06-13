"""Tests for S4.6.1–S4.7.4 — Channel Abstraction + all transport adapters.

Covers:
    - InboundChannelMessage immutability and construction
    - Channel protocol conformance
    - CLIChannel (receive, normalize, send, validation)
    - CLITUI stub
    - TUIChannel (receive, normalize, send, build_screen, validation)
    - TUIPanel / TUIStatusBar / TUIScreen data models
    - WebChannel (receive, normalize, send, validation, models)
    - WebSocketChannel (receive, normalize, send)
    - WebhookChannel (receive, normalize, send, validation)
    - SlackChannel (receive, normalize, send, validation)
    - MailChannel (receive, normalize, send, validation)
    - ChannelRegistry register / get / names / KeyError
    - register_cli_channel / register_web_channel / register_websocket_channel / register_webhook_channel / register_slack_channel / register_mail_channel convenience
    - Gateway entrypoint (process_channel_input, handle_web_request, handle_ws_message, handle_webhook_post, handle_slack_event, handle_mail_message)
"""

from __future__ import annotations

import time
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from src.platform.runtime.channels import (
    Channel,
    CLIChannel,
    CLITUI,
    InboundChannelMessage,
    MailChannel,
    SlackChannel,
    TUIChannel,
    TUIPanel,
    TUIScreen,
    TUIStatusBar,
    WebChannel,
    WebRequest,
    WebResponse,
    WebSocketChannel,
    WebhookChannel,
    WebhookEvent,
    ChannelRegistry,
    register_cli_channel,
    register_mail_channel,
    register_slack_channel,
    register_tui_channel,
    register_web_channel,
    register_websocket_channel,
    register_webhook_channel,
)
from src.platform.runtime.gateway_entrypoint import (
    process_channel_input,
    handle_web_request,
    handle_ws_message,
    handle_webhook_post,
    handle_slack_event,
    handle_mail_message,
)


# ===================================================================
# InboundChannelMessage
# ===================================================================

class TestInboundChannelMessage:
    """InboundChannelMessage dataclass — immutability and construction."""

    def test_construct(self) -> None:
        ts = time.time()
        msg = InboundChannelMessage(
            channel="cli",
            sender="alice",
            payload={"text": "hello"},
            timestamp=ts,
        )
        assert msg.channel == "cli"
        assert msg.sender == "alice"
        assert msg.payload == {"text": "hello"}
        assert msg.timestamp == ts

    def test_immutable(self) -> None:
        msg = InboundChannelMessage(
            channel="test", sender=None, payload={}, timestamp=0.0,
        )
        with pytest.raises(FrozenInstanceError):
            msg.payload = {"new": "value"}  # type: ignore[misc]

    def test_sender_none(self) -> None:
        msg = InboundChannelMessage(
            channel="anon", sender=None, payload={}, timestamp=0.0,
        )
        assert msg.sender is None

    def test_repr(self) -> None:
        msg = InboundChannelMessage(
            channel="cli", sender="bob", payload={"k": "v"}, timestamp=1.0,
        )
        r = repr(msg)
        assert "InboundChannelMessage" in r
        assert "cli" in r
        assert "bob" in r


# ===================================================================
# Channel protocol — structural typing
# ===================================================================

class TestChannelProtocol:
    """Channel protocol conformance (structural / @runtime_checkable)."""

    def test_isinstance_check(self) -> None:
        """CLIChannel should be an instance of Channel (runtime_checkable)."""
        assert isinstance(CLIChannel(clock=time.time), Channel)

    def test_non_channel_is_not_instance(self) -> None:
        assert not isinstance(42, Channel)


# ===================================================================
# CLIChannel
# ===================================================================

class TestCLIChannel:
    """CLIChannel — receive, normalize, send, validation."""

    def setup_method(self) -> None:
        self.clock = iter([1000.0, 1001.0, 1002.0]).__next__
        self.ch = CLIChannel(clock=self.clock)

    # -- receive -------------------------------------------------------

    def test_receive_minimal(self) -> None:
        msg = self.ch.receive({"text": "hello"})
        assert isinstance(msg, InboundChannelMessage)
        assert msg.channel == "cli"
        assert msg.sender is None
        assert msg.payload == {"text": "hello"}
        assert msg.timestamp == 1000.0

    def test_receive_with_sender(self) -> None:
        msg = self.ch.receive({"text": "deploy", "sender": "alice"})
        assert msg.sender == "alice"
        assert msg.payload == {"text": "deploy"}

    def test_receive_uses_clock(self) -> None:
        msg1 = self.ch.receive({"text": "a"})
        msg2 = self.ch.receive({"text": "b"})
        assert msg1.timestamp == 1000.0
        assert msg2.timestamp == 1001.0

    def test_receive_raises_on_non_dict(self) -> None:
        with pytest.raises(TypeError, match="dict"):
            self.ch.receive("just a string")  # type: ignore[arg-type]

    def test_receive_raises_on_missing_text(self) -> None:
        with pytest.raises(ValueError, match="text"):
            self.ch.receive({"sender": "bob"})

    def test_receive_raises_on_empty_text(self) -> None:
        with pytest.raises(ValueError, match="text"):
            self.ch.receive({"text": "   "})

    def test_receive_raises_on_wrong_sender_type(self) -> None:
        with pytest.raises(TypeError, match="sender"):
            self.ch.receive({"text": "hi", "sender": 42})

    def test_default_clock(self) -> None:
        ch_default = CLIChannel()
        msg = ch_default.receive({"text": "default"})
        assert isinstance(msg.timestamp, float)
        assert msg.timestamp > 0

    # -- normalize -----------------------------------------------------

    def test_normalize(self) -> None:
        msg = self.ch.receive({"text": "run tests"})
        norm = self.ch.normalize(msg)
        assert norm == {
            "input": "run tests",
            "metadata": {
                "channel": "cli",
                "sender": None,
                "received_at": 1000.0,
            },
        }

    def test_normalize_preserves_sender(self) -> None:
        msg = self.ch.receive({"text": "status", "sender": "bob"})
        norm = self.ch.normalize(msg)
        assert norm["metadata"]["sender"] == "bob"

    # -- send ----------------------------------------------------------

    def test_send(self) -> None:
        result = self.ch.send({"output": "done", "metadata": {"key": "val"}})
        assert result == {
            "text": "done",
            "metadata": {"key": "val"},
        }

    def test_send_handles_empty_output(self) -> None:
        result = self.ch.send({"metadata": {}})
        assert result["text"] == ""
        assert result["metadata"] == {}

    def test_send_handles_no_metadata(self) -> None:
        result = self.ch.send({"output": "ok"})
        assert result["text"] == "ok"
        assert result["metadata"] == {}


# ===================================================================
# CLITUI stub
# ===================================================================

class TestCLITUI:
    """CLITUI — pure-logic placeholder."""

    def test_render(self) -> None:
        tui = CLITUI()
        result = tui.render({"output": "hello", "metadata": {}})
        assert result == {
            "rendered": True,
            "content": {"output": "hello", "metadata": {}},
        }


# ===================================================================
# ChannelRegistry
# ===================================================================

class TestChannelRegistry:
    """ChannelRegistry register / get / names / KeyError."""

    def setup_method(self) -> None:
        self.registry = ChannelRegistry()

    def test_register_and_get(self) -> None:
        ch = CLIChannel()
        self.registry.register("cli", ch)
        assert self.registry.get("cli") is ch

    def test_get_unknown_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="unknown"):
            self.registry.get("unknown")

    def test_names(self) -> None:
        self.registry.register("cli", CLIChannel())
        self.registry.register("http", CLIChannel())
        assert set(self.registry.names) == {"cli", "http"}

    def test_names_empty(self) -> None:
        assert self.registry.names == ()

    def test_register_overwrites(self) -> None:
        a = CLIChannel()
        b = CLIChannel()
        self.registry.register("cli", a)
        self.registry.register("cli", b)
        assert self.registry.get("cli") is b


# ===================================================================
# register_cli_channel convenience
# ===================================================================

class TestRegisterCliChannel:
    """register_cli_channel — convenience helper."""

    def test_registers_cli_channel(self) -> None:
        registry = ChannelRegistry()
        register_cli_channel(registry)
        ch = registry.get("cli")
        assert isinstance(ch, CLIChannel)

    def test_registered_channel_processes_input(self) -> None:
        registry = ChannelRegistry()
        register_cli_channel(registry)
        result = process_channel_input(registry, "cli", {"text": "hello"})
        assert result is not None
        assert result["input"] == "hello"


# ===================================================================
# TUI data models
# ===================================================================


class TestTUIPanel:
    """TUIPanel data model — construction and immutability."""

    def test_construct(self) -> None:
        panel = TUIPanel(
            panel_id="workers",
            title="WORKERS",
            lines=(("worker-01  busy", "cyan"), ("worker-02  idle", "dim")),
            style_hint="default",
        )
        assert panel.panel_id == "workers"
        assert panel.title == "WORKERS"
        assert len(panel.lines) == 2
        assert panel.style_hint == "default"

    def test_immutable(self) -> None:
        panel = TUIPanel(panel_id="x", title="X", lines=())
        with pytest.raises(FrozenInstanceError):
            panel.panel_id = "y"  # type: ignore[misc]

    def test_default_style(self) -> None:
        panel = TUIPanel(panel_id="x", title="X", lines=())
        assert panel.style_hint == "default"


class TestTUIStatusBar:
    """TUIStatusBar data model — construction."""

    def test_construct(self) -> None:
        bar = TUIStatusBar(
            segments=(("Online", "green"), (" | ", "dim"), ("Jobs: 5", "dim"))
        )
        assert len(bar.segments) == 3

    def test_empty_segments(self) -> None:
        bar = TUIStatusBar(segments=())
        assert bar.segments == ()


class TestTUIScreen:
    """TUIScreen data model — construction, immutability, with_updated_panel."""

    def test_construct(self) -> None:
        panel = TUIPanel(panel_id="w", title="W", lines=())
        screen = TUIScreen(panels=(panel,))
        assert len(screen.panels) == 1
        assert screen.title == "VAI — Stratum-4 Operator Console"
        assert screen.status_bar is None

    def test_immutable(self) -> None:
        screen = TUIScreen(panels=())
        with pytest.raises(FrozenInstanceError):
            screen.panels = (TUIPanel(panel_id="x", title="X", lines=()),)  # type: ignore[misc]

    def test_with_updated_panel_updates_matching(self) -> None:
        p1 = TUIPanel(panel_id="a", title="A", lines=(("old", "dim"),))
        p2 = TUIPanel(panel_id="b", title="B", lines=(("keep", "dim"),))
        screen = TUIScreen(panels=(p1, p2))

        updated = screen.with_updated_panel("a", title="A (updated)", lines=(("new", "cyan"),))
        assert updated.panels[0].title == "A (updated)"
        assert updated.panels[0].lines == (("new", "cyan"),)
        # Unchanged panel preserved
        assert updated.panels[1].title == "B"
        # Original unchanged
        assert screen.panels[0].title == "A"

    def test_with_updated_panel_no_match_returns_copy(self) -> None:
        p1 = TUIPanel(panel_id="a", title="A", lines=())
        screen = TUIScreen(panels=(p1,))
        updated = screen.with_updated_panel("nonexistent", title="X")
        assert len(updated.panels) == 1
        assert updated.panels[0].title == "A"

    def test_with_updated_panel_preserves_style_hint(self) -> None:
        p1 = TUIPanel(panel_id="a", title="A", lines=(), style_hint="alert")
        screen = TUIScreen(panels=(p1,))
        updated = screen.with_updated_panel("a", title="A2")
        assert updated.panels[0].style_hint == "alert"

    def test_with_updated_panel_respects_explicit_style_hint(self) -> None:
        p1 = TUIPanel(panel_id="a", title="A", lines=(), style_hint="default")
        screen = TUIScreen(panels=(p1,))
        updated = screen.with_updated_panel("a", style_hint="highlight")
        assert updated.panels[0].style_hint == "highlight"

    def test_with_status_bar(self) -> None:
        bar = TUIStatusBar(segments=(("ok", "green"),))
        screen = TUIScreen(panels=(), status_bar=bar)
        assert screen.status_bar is not None
        assert screen.status_bar.segments[0] == ("ok", "green")

    def test_with_custom_title(self) -> None:
        screen = TUIScreen(panels=(), title="Custom")
        assert screen.title == "Custom"


# ===================================================================
# TUIChannel
# ===================================================================


class TestTUIChannel:
    """TUIChannel — receive, normalize, send, build_screen, validation."""

    def setup_method(self) -> None:
        self.clock = iter([1000.0, 1001.0, 1002.0]).__next__
        self.ch = TUIChannel(clock=self.clock)

    # -- receive -------------------------------------------------------

    def test_receive_minimal(self) -> None:
        msg = self.ch.receive({"action": "submit"})
        assert isinstance(msg, InboundChannelMessage)
        assert msg.channel == "tui"
        assert msg.sender is None
        assert msg.payload["action"] == "submit"
        assert msg.payload["data"] == {}
        assert msg.timestamp == 1000.0

    def test_receive_with_sender_and_data(self) -> None:
        msg = self.ch.receive(
            {"action": "select_job", "data": {"job_id": "abc"}, "sender": "alice"}
        )
        assert msg.sender == "alice"
        assert msg.payload["data"] == {"job_id": "abc"}

    def test_receive_uses_clock(self) -> None:
        msg1 = self.ch.receive({"action": "a"})
        msg2 = self.ch.receive({"action": "b"})
        assert msg1.timestamp == 1000.0
        assert msg2.timestamp == 1001.0

    def test_receive_raises_on_non_dict(self) -> None:
        with pytest.raises(TypeError, match="dict"):
            self.ch.receive("just a string")  # type: ignore[arg-type]

    def test_receive_raises_on_missing_action(self) -> None:
        with pytest.raises(ValueError, match="action"):
            self.ch.receive({"sender": "bob"})

    def test_receive_raises_on_empty_action(self) -> None:
        with pytest.raises(ValueError, match="action"):
            self.ch.receive({"action": "   "})

    def test_receive_raises_on_wrong_sender_type(self) -> None:
        with pytest.raises(TypeError, match="sender"):
            self.ch.receive({"action": "go", "sender": 42})

    def test_default_clock(self) -> None:
        ch_default = TUIChannel()
        msg = ch_default.receive({"action": "default"})
        assert isinstance(msg.timestamp, float)
        assert msg.timestamp > 0

    def test_receive_empty_data_defaults_to_dict(self) -> None:
        msg = self.ch.receive({"action": "quit"})
        assert msg.payload["data"] == {}

    # -- normalize -----------------------------------------------------

    def test_normalize(self) -> None:
        msg = self.ch.receive({"action": "refresh"})
        norm = self.ch.normalize(msg)
        assert norm["input"] == "refresh"
        assert norm["metadata"]["channel"] == "tui"
        assert norm["metadata"]["sender"] is None
        assert norm["metadata"]["received_at"] == 1000.0

    def test_normalize_preserves_event_data(self) -> None:
        msg = self.ch.receive({"action": "select_job", "data": {"job_id": "abc"}})
        norm = self.ch.normalize(msg)
        assert norm["metadata"]["event_data"] == {"job_id": "abc"}

    def test_normalize_preserves_sender(self) -> None:
        msg = self.ch.receive({"action": "go", "sender": "bob"})
        norm = self.ch.normalize(msg)
        assert norm["metadata"]["sender"] == "bob"

    # -- send ----------------------------------------------------------

    def test_send_with_screen(self) -> None:
        result = self.ch.send({"screen": {"panels": []}})
        assert result["screen"]["panels"] == []

    def test_send_default_screen(self) -> None:
        result = self.ch.send({})
        screen = result["screen"]
        assert len(screen["panels"]) == 3  # workers, jobs, scheduling (heartbeats via build_screen only)
        assert screen["title"] == "VAI — Stratum-4 Operator Console"
        assert screen["status_bar"] is not None

    def test_send_passthrough(self) -> None:
        custom = {"panels": [], "title": "Custom"}
        result = self.ch.send({"screen": custom})
        assert result["screen"] is custom

    # -- build_screen --------------------------------------------------

    def test_build_screen_with_workers(self) -> None:
        workers = [
            {"worker_id": "w1", "status": "busy", "active_job_id": "job-1"},
            {"worker_id": "w2", "status": "idle", "active_job_id": None},
        ]
        result = self.ch.build_screen(workers=workers, jobs=[])
        panels = result["screen"]["panels"]
        # Should have 4 panels
        worker_panel = next(p for p in panels if p["panel_id"] == "workers")
        assert "w1" in str(worker_panel)
        assert "w2" in str(worker_panel)
        assert "2" in worker_panel["title"]  # count

    def test_build_screen_with_jobs(self) -> None:
        jobs = [
            {"job_id": "j1", "priority": 5, "status": "running"},
            {"job_id": "j2", "priority": 1, "status": "pending"},
        ]
        result = self.ch.build_screen(workers=[], jobs=jobs)
        panels = result["screen"]["panels"]
        job_panel = next(p for p in panels if p["panel_id"] == "jobs")
        assert "j1" in str(job_panel)
        assert "j2" in str(job_panel)
        assert "2" in job_panel["title"]

    def test_build_screen_with_scheduling(self) -> None:
        scheduling = {
            "mode": "PRIORITY",
            "decision": {"job_id": "j1", "reason": "highest priority"},
        }
        workers = [{"worker_id": "w1", "status": "idle"}]
        result = self.ch.build_screen(workers=workers, jobs=[], scheduling=scheduling)
        panels = result["screen"]["panels"]
        sched_panel = next(p for p in panels if p["panel_id"] == "scheduling")
        text = str(sched_panel)
        assert "PRIORITY" in text or "Mode" in text

    def test_build_screen_with_heartbeats(self) -> None:
        heartbeats = {"interval_seconds": 1.0, "last_seen_ago": 0.3, "healthy": True}
        result = self.ch.build_screen(workers=[], jobs=[], heartbeats=heartbeats)
        panels = result["screen"]["panels"]
        hb_panel = next(p for p in panels if p["panel_id"] == "heartbeats")
        text = str(hb_panel)
        assert "Healthy" in text

    def test_build_screen_heartbeats_unhealthy(self) -> None:
        heartbeats = {
            "interval_seconds": 1.0,
            "last_seen_ago": 6.0,
            "healthy": False,
        }
        result = self.ch.build_screen(
            workers=[], jobs=[], scheduling=None, heartbeats=heartbeats
        )
        panels = result["screen"]["panels"]
        hb_panel = next(p for p in panels if p["panel_id"] == "heartbeats")
        text = str(hb_panel)
        assert "Unhealthy" in text

    def test_build_screen_empty(self) -> None:
        result = self.ch.build_screen(workers=[], jobs=[])
        panels = result["screen"]["panels"]
        assert len(panels) == 4
        # Worker panel shows "no workers"
        worker_panel = next(p for p in panels if p["panel_id"] == "workers")
        assert "no workers" in str(worker_panel)
        # Status bar
        bar = result["screen"]["status_bar"]
        assert "Workers: 0" in str(bar)
        assert "Jobs: 0" in str(bar)

    def test_build_screen_status_bar_shortcuts(self) -> None:
        workers = [{"worker_id": "w1", "status": "busy"}]
        result = self.ch.build_screen(workers=workers, jobs=[])
        bar = result["screen"]["status_bar"]
        text = str(bar)
        assert "Workers: 1" in text
        assert "q: Quit" in text
        assert "r: Refresh" in text

    # -- Channel protocol conformance ----------------------------------

    def test_isinstance_channel(self) -> None:
        assert isinstance(TUIChannel(clock=self.clock), Channel)


# ===================================================================
# register_tui_channel convenience
# ===================================================================


class TestRegisterTuiChannel:
    """register_tui_channel — convenience helper."""

    def test_registers_tui_channel(self) -> None:
        registry = ChannelRegistry()
        register_tui_channel(registry)
        ch = registry.get("tui")
        assert isinstance(ch, TUIChannel)

    def test_registered_channel_processes_input(self) -> None:
        registry = ChannelRegistry()
        register_tui_channel(registry)
        result = process_channel_input(registry, "tui", {"action": "submit"})
        assert result is not None
        assert result["input"] == "submit"

    def test_custom_clock_passed_through(self) -> None:
        registry = ChannelRegistry()
        clock = iter([99.0]).__next__
        register_tui_channel(registry, clock=clock)
        ch = registry.get("tui")
        msg = ch.receive({"action": "test"})
        assert msg.timestamp == 99.0


# ===================================================================
# Gateway entrypoint
# ===================================================================

class TestProcessChannelInput:
    """process_channel_input — integration stub."""

    def setup_method(self) -> None:
        self.registry = ChannelRegistry()
        self.registry.register("cli", CLIChannel())

    def test_processes_input(self) -> None:
        result = process_channel_input(self.registry, "cli", {"text": "say hello"})
        assert result is not None
        assert result["input"] == "say hello"

    def test_unknown_channel_returns_none(self) -> None:
        result = process_channel_input(self.registry, "nope", {"text": "data"})
        assert result is None

    def test_empty_registry_returns_none(self) -> None:
        empty = ChannelRegistry()
        result = process_channel_input(empty, "cli", {"text": "data"})
        assert result is None


# ===================================================================
# WebChannel
# ===================================================================

class TestWebChannel:
    """WebChannel — receive, normalize, send."""

    def setup_method(self) -> None:
        self.clock = iter([100.0, 200.0, 300.0]).__next__
        self.ch = WebChannel(clock=self.clock)

    # -- receive -------------------------------------------------------

    def test_receive_basic(self) -> None:
        msg = self.ch.receive({"input": "deploy app"})
        assert msg.channel == "web"
        assert msg.sender is None
        assert msg.payload["input"] == "deploy app"
        assert msg.payload["metadata"] == {}
        assert msg.timestamp == 100.0

    def test_receive_with_sender(self) -> None:
        msg = self.ch.receive({"input": "hello", "sender": "alice"})
        assert msg.sender == "alice"
        assert msg.timestamp == 100.0

    def test_receive_with_metadata(self) -> None:
        msg = self.ch.receive({"input": "hello", "metadata": {"source": "dashboard"}})
        assert msg.payload["metadata"] == {"source": "dashboard"}

    def test_receive_not_a_dict(self) -> None:
        with pytest.raises(TypeError, match="requires a dict"):
            self.ch.receive("string")

    def test_receive_missing_input(self) -> None:
        with pytest.raises(ValueError, match="'input' field"):
            self.ch.receive({"text": "hello"})

    def test_receive_empty_input(self) -> None:
        with pytest.raises(ValueError, match="'input' field"):
            self.ch.receive({"input": ""})

    def test_receive_invalid_sender(self) -> None:
        with pytest.raises(TypeError, match="'sender' must be a string"):
            self.ch.receive({"input": "hi", "sender": 42})

    def test_receive_invalid_metadata(self) -> None:
        with pytest.raises(TypeError, match="'metadata' must be a dict"):
            self.ch.receive({"input": "hi", "metadata": "nope"})

    # -- normalize -----------------------------------------------------

    def test_normalize(self) -> None:
        msg = InboundChannelMessage(
            channel="web",
            sender="alice",
            payload={"input": "deploy", "metadata": {"source": "api"}},
            timestamp=100.0,
        )
        result = self.ch.normalize(msg)
        assert result["input"] == "deploy"
        assert result["metadata"]["channel"] == "web"
        assert result["metadata"]["sender"] == "alice"
        assert result["metadata"]["source"] == "api"

    def test_normalize_no_metadata(self) -> None:
        msg = InboundChannelMessage(
            channel="web",
            sender=None,
            payload={"input": "deploy", "metadata": {}},
            timestamp=100.0,
        )
        result = self.ch.normalize(msg)
        assert result["input"] == "deploy"
        assert result["metadata"]["sender"] is None

    # -- send ----------------------------------------------------------

    def test_send(self) -> None:
        result = self.ch.send({"output": "done", "metadata": {"job_id": "j-1"}})
        assert result["output"] == "done"
        assert result["metadata"] == {"job_id": "j-1"}

    def test_send_empty(self) -> None:
        result = self.ch.send({})
        assert result["output"] == ""
        assert result["metadata"] == {}

    # -- WebRequest / WebResponse models -------------------------------

    def test_web_request_model(self) -> None:
        req = WebRequest(input="deploy", sender="alice", metadata={"env": "prod"})
        assert req.input == "deploy"
        assert req.sender == "alice"
        assert req.metadata == {"env": "prod"}

    def test_web_request_defaults(self) -> None:
        req = WebRequest(input="hello")
        assert req.sender is None
        assert req.metadata is None

    def test_web_response_model(self) -> None:
        resp = WebResponse(output="done", metadata={"job_id": "j-1"})
        assert resp.output == "done"
        assert resp.metadata == {"job_id": "j-1"}

    def test_web_response_defaults(self) -> None:
        resp = WebResponse(output="ok")
        assert resp.metadata is None

    # -- Channel protocol conformance ----------------------------------

    def test_is_channel(self) -> None:
        assert isinstance(self.ch, Channel)

    # -- clock independence --------------------------------------------

    def test_receive_default_clock(self) -> None:
        ch = WebChannel()
        msg = ch.receive({"input": "hello"})
        assert isinstance(msg.timestamp, float)
        assert msg.timestamp > 0


class TestRegisterWebChannel:
    """register_web_channel convenience."""

    def test_registers_under_web(self) -> None:
        registry = ChannelRegistry()
        register_web_channel(registry)
        assert "web" in registry.names
        assert isinstance(registry.get("web"), WebChannel)

    def test_registered_channel_works(self) -> None:
        registry = ChannelRegistry()
        register_web_channel(registry)
        msg = registry.get("web").receive({"input": "hello"})
        assert msg.channel == "web"

    def test_default_clock(self) -> None:
        registry = ChannelRegistry()
        register_web_channel(registry)
        ch = registry.get("web")
        assert ch._clock is not None


class TestHandleWebRequest:
    """handle_web_request — gateway convenience."""

    def setup_method(self) -> None:
        self.registry = ChannelRegistry()
        register_web_channel(self.registry)

    def test_handles_request(self) -> None:
        result = handle_web_request(self.registry, {"input": "deploy"})
        assert result is not None
        assert result["input"] == "deploy"
        assert result["metadata"]["channel"] == "web"

    def test_unregistered_returns_none(self) -> None:
        empty = ChannelRegistry()
        result = handle_web_request(empty, {"input": "deploy"})
        assert result is None


# ===================================================================
# WebSocket Channel
# ===================================================================


class TestWebSocketChannel:
    """WebSocketChannel — receive, normalize, send."""

    def setup_method(self) -> None:
        self.clock = iter([100.0, 101.0, 102.0])
        self.channel = WebSocketChannel(clock=lambda: next(self.clock))

    def test_receive_basic(self) -> None:
        msg = self.channel.receive({"text": "ping"})
        assert msg.channel == "ws"
        assert msg.sender is None
        assert msg.payload["text"] == "ping"
        assert msg.payload["message_type"] == "text"
        assert msg.timestamp == 100.0

    def test_receive_with_sender(self) -> None:
        msg = self.channel.receive({"text": "hello", "sender": "node1"})
        assert msg.sender == "node1"
        assert msg.payload["message_type"] == "text"

    def test_receive_with_message_type(self) -> None:
        msg = self.channel.receive({"text": "data", "message_type": "binary"})
        assert msg.payload["message_type"] == "binary"

    def test_receive_raises_on_non_dict(self) -> None:
        with pytest.raises(TypeError, match="requires a dict"):
            self.channel.receive("bad input")  # type: ignore[arg-type]

    def test_receive_raises_on_missing_text(self) -> None:
        with pytest.raises(ValueError, match="requires a 'text' field"):
            self.channel.receive({"sender": "x"})

    def test_receive_raises_on_empty_text(self) -> None:
        with pytest.raises(ValueError, match="requires a 'text' field"):
            self.channel.receive({"text": ""})

    def test_normalize_minimal(self) -> None:
        msg = self.channel.receive({"text": "hello"})
        result = self.channel.normalize(msg)
        assert result["input"] == "hello"
        assert result["metadata"]["channel"] == "ws"
        assert result["metadata"]["sender"] is None
        assert result["metadata"]["message_type"] == "text"

    def test_normalize_with_sender(self) -> None:
        msg = self.channel.receive({"text": "hello", "sender": "alice"})
        result = self.channel.normalize(msg)
        assert result["input"] == "hello"
        assert result["metadata"]["sender"] == "alice"

    def test_send_basic(self) -> None:
        result = self.channel.send({"output": "pong"})
        assert result["text"] == "pong"
        assert result["message_type"] == "text"
        assert result["metadata"] == {}

    def test_send_with_metadata(self) -> None:
        result = self.channel.send({"output": "ack", "metadata": {"job_id": "j-1"}})
        assert result["text"] == "ack"
        assert result["metadata"]["job_id"] == "j-1"

    def test_send_defaults(self) -> None:
        result = self.channel.send({})
        assert result["text"] == ""
        assert result["message_type"] == "text"


# ===================================================================
# Register WebSocket Channel
# ===================================================================


class TestRegisterWebsocketChannel:
    """register_websocket_channel convenience helper."""

    def test_registers_under_ws(self) -> None:
        registry = ChannelRegistry()
        register_websocket_channel(registry)
        channel = registry.get("ws")
        assert isinstance(channel, WebSocketChannel)

    def test_registered_channel_works(self) -> None:
        registry = ChannelRegistry()
        register_websocket_channel(registry)
        result = process_channel_input(registry, "ws", {"text": "hi"})
        assert result is not None
        assert result["input"] == "hi"
        assert result["metadata"]["channel"] == "ws"


# ===================================================================
# Handle WS Message (gateway convenience)
# ===================================================================


class TestHandleWsMessage:
    """handle_ws_message — gateway convenience."""

    def setup_method(self) -> None:
        self.registry = ChannelRegistry()
        register_websocket_channel(self.registry)

    def test_handles_message(self) -> None:
        result = handle_ws_message(self.registry, {"text": "ping"})
        assert result is not None
        assert result["input"] == "ping"
        assert result["metadata"]["channel"] == "ws"

    def test_unregistered_returns_none(self) -> None:
        empty = ChannelRegistry()
        result = handle_ws_message(empty, {"text": "data"})
        assert result is None


# ===================================================================
# Webhook Channel
# ===================================================================


class TestWebhookChannel:
    """WebhookChannel — receive, normalize, send, validation."""

    def setup_method(self) -> None:
        self.clock = iter([200.0, 201.0, 202.0])
        self.channel = WebhookChannel(clock=lambda: next(self.clock))

    def test_webhook_event_frozen(self) -> None:
        event = WebhookEvent(source="github", payload={"action": "push"}, sender="bot")
        assert event.source == "github"
        assert event.payload == {"action": "push"}
        assert event.sender == "bot"

    def test_webhook_event_immutable(self) -> None:
        event = WebhookEvent("github", {}, None)
        with pytest.raises(FrozenInstanceError):
            event.source = "stripe"  # type: ignore[misc]

    def test_receive_minimal(self) -> None:
        msg = self.channel.receive({
            "source": "github",
            "payload": {"event": "push"},
        })
        assert msg.channel == "webhook"
        assert msg.sender is None
        assert msg.payload["source"] == "github"
        assert msg.payload["payload"] == {"event": "push"}
        assert msg.timestamp == 200.0

    def test_receive_with_sender(self) -> None:
        msg = self.channel.receive({
            "source": "whatsapp",
            "payload": {"text": "hello"},
            "sender": "user-123",
        })
        assert msg.sender == "user-123"
        assert msg.payload["source"] == "whatsapp"

    def test_receive_raises_on_non_dict(self) -> None:
        with pytest.raises(TypeError, match="requires a dict"):
            self.channel.receive("bad input")  # type: ignore[arg-type]

    def test_receive_raises_on_missing_source(self) -> None:
        with pytest.raises(ValueError, match="requires a 'source' field"):
            self.channel.receive({"payload": {}})

    def test_receive_raises_on_empty_source(self) -> None:
        with pytest.raises(ValueError, match="requires a 'source' field"):
            self.channel.receive({"source": "", "payload": {}})

    def test_receive_raises_on_missing_payload(self) -> None:
        with pytest.raises(ValueError, match="requires a 'payload' field"):
            self.channel.receive({"source": "github"})

    def test_receive_raises_on_bad_sender_type(self) -> None:
        with pytest.raises(TypeError, match="'sender' must be a string"):
            self.channel.receive({
                "source": "github",
                "payload": {},
                "sender": 42,
            })

    def test_normalize_minimal(self) -> None:
        msg = self.channel.receive({
            "source": "github",
            "payload": {"event": "push"},
        })
        result = self.channel.normalize(msg)
        assert result["input"] == {"event": "push"}
        assert result["metadata"]["channel"] == "webhook"
        assert result["metadata"]["source"] == "github"
        assert result["metadata"]["sender"] is None

    def test_normalize_with_sender(self) -> None:
        msg = self.channel.receive({
            "source": "stripe",
            "payload": {"type": "charge.completed"},
            "sender": "stripe-webhook",
        })
        result = self.channel.normalize(msg)
        assert result["metadata"]["sender"] == "stripe-webhook"

    def test_send_basic(self) -> None:
        result = self.channel.send({"output": "Processed"})
        assert result["status"] == "ok"
        assert result["response"] == "Processed"
        assert result["metadata"] == {}

    def test_send_with_metadata(self) -> None:
        result = self.channel.send({
            "output": "Queued",
            "metadata": {"job_id": "j-1"},
        })
        assert result["status"] == "ok"
        assert result["response"] == "Queued"
        assert result["metadata"]["job_id"] == "j-1"

    def test_send_defaults(self) -> None:
        result = self.channel.send({})
        assert result["status"] == "ok"
        assert result["response"] == ""
        assert result["metadata"] == {}


# ===================================================================
# Register Webhook Channel
# ===================================================================


class TestRegisterWebhookChannel:
    """register_webhook_channel convenience helper."""

    def test_registers_under_webhook(self) -> None:
        registry = ChannelRegistry()
        register_webhook_channel(registry)
        channel = registry.get("webhook")
        assert isinstance(channel, WebhookChannel)

    def test_registered_channel_works(self) -> None:
        registry = ChannelRegistry()
        register_webhook_channel(registry)
        result = process_channel_input(registry, "webhook", {
            "source": "generic",
            "payload": {"msg": "hello"},
        })
        assert result is not None
        assert result["metadata"]["channel"] == "webhook"


# ===================================================================
# Handle Webhook Post (gateway convenience)
# ===================================================================


class TestHandleWebhookPost:
    """handle_webhook_post — gateway convenience."""

    def setup_method(self) -> None:
        self.registry = ChannelRegistry()
        register_webhook_channel(self.registry)

    def test_handles_post(self) -> None:
        result = handle_webhook_post(self.registry, {
            "source": "github",
            "payload": {"action": "push"},
        })
        assert result is not None
        assert result["metadata"]["channel"] == "webhook"
        assert result["metadata"]["source"] == "github"

    def test_unregistered_returns_none(self) -> None:
        empty = ChannelRegistry()
        result = handle_webhook_post(empty, {
            "source": "github",
            "payload": {},
        })
        assert result is None


# ===================================================================
# Slack Channel
# ===================================================================


class TestSlackChannel:
    """SlackChannel — receive, normalize, send, validation.

    .. todo::

        Integration test: requires a real Slack workspace + app with
        Event Subscriptions.  The unit tests here validate the pure-logic
        receive/normalize/send pipeline only.
    """

    def setup_method(self) -> None:
        self.clock = iter([300.0, 301.0, 302.0])
        self.channel = SlackChannel(clock=lambda: next(self.clock))

    def test_receive_minimal(self) -> None:
        msg = self.channel.receive({"text": "deploy"})
        assert msg.channel == "slack"
        assert msg.sender is None
        assert msg.payload["text"] == "deploy"
        assert msg.timestamp == 300.0

    def test_receive_with_sender(self) -> None:
        msg = self.channel.receive({"text": "hello", "sender": "U12345"})
        assert msg.sender == "U12345"
        assert msg.payload["text"] == "hello"

    def test_receive_with_channel_and_team(self) -> None:
        msg = self.channel.receive({
            "text": "status",
            "sender": "U999",
            "channel": "C67890",
            "team": "T11111",
        })
        assert msg.payload["channel"] == "C67890"
        assert msg.payload["team"] == "T11111"
        assert msg.sender == "U999"

    def test_receive_raises_on_non_dict(self) -> None:
        with pytest.raises(TypeError, match="requires a dict"):
            self.channel.receive("bad")  # type: ignore[arg-type]

    def test_receive_raises_on_missing_text(self) -> None:
        with pytest.raises(ValueError, match="requires a 'text' field"):
            self.channel.receive({"sender": "U1"})

    def test_receive_raises_on_empty_text(self) -> None:
        with pytest.raises(ValueError, match="requires a 'text' field"):
            self.channel.receive({"text": ""})

    def test_receive_raises_on_bad_sender_type(self) -> None:
        with pytest.raises(TypeError, match="'sender' must be a string"):
            self.channel.receive({"text": "hi", "sender": 42})

    def test_receive_raises_on_bad_channel_type(self) -> None:
        with pytest.raises(TypeError, match="'channel' must be a string"):
            self.channel.receive({"text": "hi", "channel": 42})

    def test_receive_raises_on_bad_team_type(self) -> None:
        with pytest.raises(TypeError, match="'team' must be a string"):
            self.channel.receive({"text": "hi", "team": 99})

    def test_normalize_minimal(self) -> None:
        msg = self.channel.receive({"text": "deploy now"})
        result = self.channel.normalize(msg)
        assert result["input"] == "deploy now"
        assert result["metadata"]["channel"] == "slack"
        assert result["metadata"]["sender"] is None
        assert "slack_channel" not in result["metadata"]
        assert "slack_team" not in result["metadata"]

    def test_normalize_with_channel(self) -> None:
        msg = self.channel.receive({
            "text": "status",
            "sender": "U1",
            "channel": "C1",
            "team": "T1",
        })
        result = self.channel.normalize(msg)
        assert result["input"] == "status"
        assert result["metadata"]["sender"] == "U1"
        assert result["metadata"]["slack_channel"] == "C1"
        assert result["metadata"]["slack_team"] == "T1"

    def test_send_basic(self) -> None:
        result = self.channel.send({"output": "done"})
        assert result["text"] == "done"
        assert result["metadata"] == {}

    def test_send_with_metadata(self) -> None:
        result = self.channel.send({
            "output": "deploying",
            "metadata": {"job_id": "j-1", "slack_channel": "C1"},
        })
        assert result["text"] == "deploying"
        assert result["channel"] == "C1"
        assert result["metadata"]["job_id"] == "j-1"

    def test_send_defaults(self) -> None:
        result = self.channel.send({})
        assert result["text"] == ""
        assert result["metadata"] == {}


# ===================================================================
# Register Slack Channel
# ===================================================================


class TestRegisterSlackChannel:
    """register_slack_channel convenience helper."""

    def test_registers_under_slack(self) -> None:
        registry = ChannelRegistry()
        register_slack_channel(registry)
        channel = registry.get("slack")
        assert isinstance(channel, SlackChannel)

    def test_registered_channel_works(self) -> None:
        registry = ChannelRegistry()
        register_slack_channel(registry)
        result = process_channel_input(registry, "slack", {"text": "hello"})
        assert result is not None
        assert result["metadata"]["channel"] == "slack"
        assert result["input"] == "hello"

    def test_default_clock(self) -> None:
        registry = ChannelRegistry()
        register_slack_channel(registry)
        ch = registry.get("slack")
        assert ch._clock is not None


# ===================================================================
# Handle Slack Event (gateway convenience)
# ===================================================================


class TestHandleSlackEvent:
    """handle_slack_event — gateway convenience."""

    def setup_method(self) -> None:
        self.registry = ChannelRegistry()
        register_slack_channel(self.registry)

    def test_handles_event(self) -> None:
        result = handle_slack_event(self.registry, {"text": "deploy"})
        assert result is not None
        assert result["input"] == "deploy"
        assert result["metadata"]["channel"] == "slack"

    def test_unregistered_returns_none(self) -> None:
        empty = ChannelRegistry()
        result = handle_slack_event(empty, {"text": "data"})
        assert result is None


# ===================================================================
# Mail Channel
# ===================================================================


class TestMailChannel:
    """MailChannel — receive, normalize, send, validation.

    .. todo::

        Integration test: requires an SMTP server (e.g. ``smtpd``) and
        an IMAP inbox for end-to-end send-and-receive testing.  The
        unit tests here validate the pure-logic pipeline only.
    """

    def setup_method(self) -> None:
        self.clock = iter([400.0, 401.0, 402.0])
        self.channel = MailChannel(clock=lambda: next(self.clock))

    def test_receive_minimal(self) -> None:
        msg = self.channel.receive({
            "from": "alice@example.com",
            "subject": "Deploy",
            "body": "Please deploy staging",
        })
        assert msg.channel == "mail"
        assert msg.sender == "alice@example.com"
        assert msg.payload["subject"] == "Deploy"
        assert msg.payload["body"] == "Please deploy staging"
        assert msg.timestamp == 400.0

    def test_receive_with_to(self) -> None:
        msg = self.channel.receive({
            "from": "bob@work.com",
            "to": "bot@vai.example",
            "subject": "Status",
            "body": "All good",
        })
        assert msg.payload["from"] == "bob@work.com"
        assert msg.payload["to"] == "bot@vai.example"
        assert msg.sender == "bob@work.com"

    def test_receive_raises_on_non_dict(self) -> None:
        with pytest.raises(TypeError, match="requires a dict"):
            self.channel.receive("bad")  # type: ignore[arg-type]

    def test_receive_raises_on_missing_from(self) -> None:
        with pytest.raises(ValueError, match="requires a 'from' field"):
            self.channel.receive({"subject": "Hi", "body": "Hello"})

    def test_receive_raises_on_empty_from(self) -> None:
        with pytest.raises(ValueError, match="requires a 'from' field"):
            self.channel.receive({"from": "", "subject": "Hi", "body": "Hello"})

    def test_receive_raises_on_missing_subject(self) -> None:
        with pytest.raises(ValueError, match="requires a 'subject' field"):
            self.channel.receive({"from": "a@b.com", "body": "Hello"})

    def test_receive_raises_on_empty_subject(self) -> None:
        with pytest.raises(ValueError, match="requires a 'subject' field"):
            self.channel.receive({"from": "a@b.com", "subject": "", "body": "Hello"})

    def test_receive_raises_on_missing_body(self) -> None:
        with pytest.raises(ValueError, match="requires a 'body' field"):
            self.channel.receive({"from": "a@b.com", "subject": "Hi"})

    def test_receive_raises_on_empty_body(self) -> None:
        with pytest.raises(ValueError, match="requires a 'body' field"):
            self.channel.receive({"from": "a@b.com", "subject": "Hi", "body": ""})

    def test_receive_raises_on_bad_to_type(self) -> None:
        with pytest.raises(TypeError, match="'to' must be a string"):
            self.channel.receive({
                "from": "a@b.com",
                "to": 42,
                "subject": "Hi",
                "body": "Hello",
            })

    def test_normalize_minimal(self) -> None:
        msg = self.channel.receive({
            "from": "alice@example.com",
            "subject": "Deploy",
            "body": "Please deploy staging",
        })
        result = self.channel.normalize(msg)
        assert result["input"] == "Deploy: Please deploy staging"
        assert result["metadata"]["channel"] == "mail"
        assert result["metadata"]["sender"] == "alice@example.com"
        assert result["metadata"]["to"] == ""
        assert result["metadata"]["subject"] == "Deploy"

    def test_normalize_with_to(self) -> None:
        msg = self.channel.receive({
            "from": "bob@work.com",
            "to": "bot@vai.example",
            "subject": "Status",
            "body": "All systems go",
        })
        result = self.channel.normalize(msg)
        assert result["input"] == "Status: All systems go"
        assert result["metadata"]["to"] == "bot@vai.example"

    def test_send_basic(self) -> None:
        result = self.channel.send({"output": "Deploying now"})
        assert result["to"] == ""
        assert result["subject"] == "Re: Your request"
        assert result["body"] == "Deploying now"
        assert result["metadata"] == {}

    def test_send_with_metadata(self) -> None:
        result = self.channel.send({
            "output": "Done",
            "metadata": {"to": "alice@example.com", "subject": "Re: Deploy"},
        })
        assert result["to"] == "alice@example.com"
        assert result["subject"] == "Re: Deploy"
        assert result["body"] == "Done"

    def test_send_defaults(self) -> None:
        result = self.channel.send({})
        assert result["body"] == ""
        assert result["subject"] == "Re: Your request"


# ===================================================================
# Register Mail Channel
# ===================================================================


class TestRegisterMailChannel:
    """register_mail_channel convenience helper."""

    def test_registers_under_mail(self) -> None:
        registry = ChannelRegistry()
        register_mail_channel(registry)
        channel = registry.get("mail")
        assert isinstance(channel, MailChannel)

    def test_registered_channel_works(self) -> None:
        registry = ChannelRegistry()
        register_mail_channel(registry)
        result = process_channel_input(registry, "mail", {
            "from": "a@b.com",
            "subject": "Hi",
            "body": "Hello",
        })
        assert result is not None
        assert result["metadata"]["channel"] == "mail"

    def test_default_clock(self) -> None:
        registry = ChannelRegistry()
        register_mail_channel(registry)
        ch = registry.get("mail")
        assert ch._clock is not None


# ===================================================================
# Handle Mail Message (gateway convenience)
# ===================================================================


class TestHandleMailMessage:
    """handle_mail_message — gateway convenience."""

    def setup_method(self) -> None:
        self.registry = ChannelRegistry()
        register_mail_channel(self.registry)

    def test_handles_message(self) -> None:
        result = handle_mail_message(self.registry, {
            "from": "alice@example.com",
            "subject": "Deploy",
            "body": "Please deploy",
        })
        assert result is not None
        assert result["input"] == "Deploy: Please deploy"
        assert result["metadata"]["channel"] == "mail"

    def test_unregistered_returns_none(self) -> None:
        empty = ChannelRegistry()
        result = handle_mail_message(empty, {
            "from": "a@b.com",
            "subject": "Hi",
            "body": "Hello",
        })
        assert result is None
