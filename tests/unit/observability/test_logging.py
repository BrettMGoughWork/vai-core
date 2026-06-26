"""Tests for S4.8.2 Logging — LogEvent, sinks, log(), LogContext, category helpers.

Covers:
- LogEvent construction, to_dict(), to_json()
- StdoutLogSink and CollectingLogSink
- log() basic emission and field coercion
- LogContext (correlation_id / trace_id propagation)
- Category helpers (log_job_state_transition, worker, queue, execution, etc.)
- register_log_sink / clear_log_sinks
- Exception hardening
"""

from __future__ import annotations

import json

import pytest

from src.platform.observability import logging as mod


# ------------------------------------------------------------------
# LogEvent
# ------------------------------------------------------------------


class TestLogEvent:
    def test_construct_defaults(self):
        event = mod.LogEvent(level="info", message="test_event")
        assert event.level == "info"
        assert event.message == "test_event"
        assert event.correlation_id == ""
        assert event.fields == {}

    def test_construct_full(self):
        event = mod.LogEvent(
            level="warning",
            message="job_state_transition",
            correlation_id="job-1",
            trace_id="trace-x",
            component="control_plane",
            fields={"job_id": "job-1", "from": "pending", "to": "running"},
        )
        assert event.level == "warning"
        assert event.correlation_id == "job-1"
        assert event.trace_id == "trace-x"

    def test_to_dict_shape(self):
        event = mod.LogEvent(
            level="error",
            message="something_failed",
            component="worker",
            fields={"reason": "timeout"},
        )
        d = event.to_dict()
        assert d["event"] == "log"
        assert d["level"] == "error"
        assert d["message"] == "something_failed"
        assert d["component"] == "worker"
        assert d["fields"] == {"reason": "timeout"}
        assert "timestamp" in d

    def test_to_json_round_trippable(self):
        event = mod.LogEvent(level="info", message="test")
        line = event.to_json()
        parsed = json.loads(line)
        assert parsed["event"] == "log"
        assert parsed["level"] == "info"

    def test_to_json_single_line(self):
        event = mod.LogEvent(level="info", message="test")
        assert "\n" not in event.to_json()


# ------------------------------------------------------------------
# StdoutLogSink
# ------------------------------------------------------------------


class TestStdoutLogSink:
    def test_accept_writes_to_stderr(self, capsys):
        sink = mod.StdoutLogSink()
        event = mod.LogEvent(level="info", message="test")
        sink.accept(event)
        captured = capsys.readouterr()
        assert "test" in captured.err

    def test_accept_never_raises(self, capsys):
        sink = mod.StdoutLogSink()
        sink.accept("bad")  # type: ignore[arg-type]
        # Should not raise


# ------------------------------------------------------------------
# CollectingLogSink
# ------------------------------------------------------------------


class TestCollectingLogSink:
    def test_collects_events(self):
        sink = mod.CollectingLogSink()
        sink.accept(mod.LogEvent(level="info", message="a"))
        sink.accept(mod.LogEvent(level="warn", message="b"))
        assert len(sink.events()) == 2

    def test_clear(self):
        sink = mod.CollectingLogSink()
        sink.accept(mod.LogEvent(level="info", message="a"))
        sink.clear()
        assert len(sink.events()) == 0

    def test_events_is_snapshot(self):
        sink = mod.CollectingLogSink()
        sink.accept(mod.LogEvent(level="info", message="a"))
        snap = sink.events()
        sink.accept(mod.LogEvent(level="info", message="b"))
        assert len(snap) == 1


# ------------------------------------------------------------------
# log() — public API
# ------------------------------------------------------------------


class TestLog:
    def test_basic_emission(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            mod.log("info", "test_event", {"key": "value"}, component="test")
            assert len(sink.events()) == 1
            ev = sink.events()[0]
            assert ev.level == "info"
            assert ev.message == "test_event"
            assert ev.fields == {"key": "value"}
            assert ev.component == "test"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_field_coercion(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            mod.log("info", "test", {"num": 42, "flag": True})
            ev = sink.events()[0]
            assert ev.fields["num"] == "42"
            assert ev.fields["flag"] == "True"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_empty_fields(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            mod.log("info", "test_event")
            assert len(sink.events()) == 1
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_never_raises_on_bad_input(self):
        mod.clear_log_sinks()
        try:
            mod.log(None, None)  # type: ignore[arg-type]
            mod.log("info", "test", {"bad": object()})
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_sink_failure_does_not_propagate(self):
        mod.clear_log_sinks()
        try:

            class BrokenSink:
                def accept(self, event):
                    raise RuntimeError("boom")

            mod.register_log_sink(BrokenSink())  # type: ignore[arg-type]
            mod.log("info", "test")
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())


# ------------------------------------------------------------------
# LogContext
# ------------------------------------------------------------------


class TestLogContext:
    def test_injects_correlation_id(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            with mod.LogContext(correlation_id="job-abc", trace_id="trace-1"):
                mod.log("info", "test", {})
            ev = sink.events()[0]
            assert ev.correlation_id == "job-abc"
            assert ev.trace_id == "trace-1"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_restores_after_exit(self):
        mod.clear_log_sinks()
        try:
            with mod.LogContext(correlation_id="inner", trace_id="t-inner"):
                pass
            assert mod.current_correlation_id() == ""
            assert mod.current_trace_id() == ""
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_nesting_restores_outer(self):
        mod.clear_log_sinks()
        try:
            with mod.LogContext(correlation_id="outer", trace_id="t-outer"):
                with mod.LogContext(correlation_id="inner", trace_id="t-inner"):
                    assert mod.current_correlation_id() == "inner"
                assert mod.current_correlation_id() == "outer"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_explicit_ids_override_context(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            with mod.LogContext(correlation_id="ctx-cid", trace_id="ctx-tid"):
                mod.log(
                    "info",
                    "test",
                    {},
                    _correlation_id="explicit-cid",
                    _trace_id="explicit-tid",
                )
            ev = sink.events()[0]
            assert ev.correlation_id == "explicit-cid"
            assert ev.trace_id == "explicit-tid"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())


# ------------------------------------------------------------------
# Category helpers
# ------------------------------------------------------------------


class TestCategoryHelpers:
    def test_log_job_state_transition(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            mod.log_job_state_transition("job-1", "pending", "running", component="cp")
            ev = sink.events()[0]
            assert ev.message == "job_state_transition"
            assert ev.fields["job_id"] == "job-1"
            assert ev.fields["from"] == "pending"
            assert ev.fields["to"] == "running"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_log_worker_activity(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            mod.log_worker_activity("w-1", "healthy", job_id="job-1")
            ev = sink.events()[0]
            assert ev.message == "worker_activity"
            assert ev.fields["worker_id"] == "w-1"
            assert ev.fields["status"] == "healthy"
            assert ev.fields["job_id"] == "job-1"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_log_queue_event(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            mod.log_queue_event("default", "enqueue", 3)
            ev = sink.events()[0]
            assert ev.message == "queue_event"
            assert ev.fields["queue"] == "default"
            assert ev.fields["action"] == "enqueue"
            assert ev.fields["depth"] == "3"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_log_execution(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            mod.log_execution("w-1", "cli", 1234.5)
            ev = sink.events()[0]
            assert ev.message == "execution"
            assert ev.fields["worker_id"] == "w-1"
            assert ev.fields["job_type"] == "cli"
            assert ev.fields["duration_ms"] == "1234"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_log_supervisor_action(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            mod.log_supervisor_action("repair", "worker_unhealthy", worker_id="w-1")
            ev = sink.events()[0]
            assert ev.message == "supervisor_action"
            assert ev.level == "warning"
            assert ev.fields["action"] == "repair"
            assert ev.fields["reason"] == "worker_unhealthy"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_log_job_created(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            from datetime import datetime, timezone
            from src.platform.runtime.job import Job
            from src.platform.runtime.job_state import JobState
            from src.platform.transport.normalization import ChannelMessage

            payload = ChannelMessage(input={"text": "hello"})
            job = Job(
                job_id="job-1",
                created_at=datetime.now(timezone.utc),
                state=JobState.PENDING,
                payload=payload,
            )
            mod.log_job_created(job)
            ev = sink.events()[0]
            assert ev.message == "job_created"
            assert ev.correlation_id == "job-1"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_log_job_started(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            from datetime import datetime, timezone
            from src.platform.runtime.job import Job
            from src.platform.runtime.job_state import JobState
            from src.platform.transport.normalization import ChannelMessage

            payload = ChannelMessage(input={"text": "hello"})
            job = Job(job_id="job-1", created_at=datetime.now(timezone.utc), state=JobState.PENDING, payload=payload)
            mod.log_job_started(job)
            ev = sink.events()[0]
            assert ev.message == "job_started"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_log_job_finished(self):
        sink = mod.CollectingLogSink()
        mod.clear_log_sinks()
        mod.register_log_sink(sink)
        try:
            from datetime import datetime, timezone
            from src.platform.runtime.job import Job
            from src.platform.runtime.job_state import JobState
            from src.platform.transport.normalization import ChannelMessage

            payload = ChannelMessage(input={"text": "hello"})
            job = Job(job_id="job-1", created_at=datetime.now(timezone.utc), state=JobState.PENDING, payload=payload)
            mod.log_job_finished(job)
            ev = sink.events()[0]
            assert ev.message == "job_finished"
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())


# ------------------------------------------------------------------
# Global sink registry
# ------------------------------------------------------------------


class TestLogSinkRegistry:
    def test_register_and_clear(self):
        mod.clear_log_sinks()
        try:
            sink = mod.CollectingLogSink()
            mod.register_log_sink(sink)
            assert len(mod._global_log_sinks) == 1  # type: ignore[attr-defined]
            mod.clear_log_sinks()
            assert len(mod._global_log_sinks) == 0  # type: ignore[attr-defined]
        finally:
            mod.clear_log_sinks()
            mod.register_log_sink(mod.StdoutLogSink())

    def test_default_sink_is_stdout(self):
        assert len(mod._global_log_sinks) >= 1  # type: ignore[attr-defined]
        assert isinstance(mod._global_log_sinks[-1], mod.StdoutLogSink)  # type: ignore[attr-defined]
