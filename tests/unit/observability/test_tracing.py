"""Tests for S4.8.3 Tracing — TraceEvent, sinks, emit_trace(), TraceContext,
category helpers, parent/child linking, stable root IDs.

Covers:
- TraceEvent construction, to_dict(), to_json()
- StdoutTraceSink and CollectingTraceSink
- emit_trace() basic and with parent_trace_id
- TraceContext (entering/exiting spans)
- Stable root trace IDs via _root_trace_id()
- Category helpers (emit_job_trace, emit_cycle_trace, emit_segment_trace)
- register_trace_sink / clear_trace_sinks
- Exception hardening
"""

from __future__ import annotations

import json

import pytest

from src.platform.observability import tracing as mod


# ------------------------------------------------------------------
# TraceEvent
# ------------------------------------------------------------------


class TestTraceEvent:
    def test_construct_defaults(self):
        event = mod.TraceEvent(trace_type="job", trace_id="t-1")
        assert event.trace_type == "job"
        assert event.trace_id == "t-1"
        assert event.parent_trace_id == ""
        assert event.component == ""
        assert event.fields == {}

    def test_construct_full(self):
        event = mod.TraceEvent(
            trace_type="cycle",
            trace_id="t-child",
            parent_trace_id="t-root",
            correlation_id="c-1",
            component="worker",
            fields={"attempt": "1", "worker_id": "w-1"},
        )
        assert event.trace_type == "cycle"
        assert event.parent_trace_id == "t-root"
        assert event.fields["attempt"] == "1"

    def test_to_dict_shape(self):
        event = mod.TraceEvent(
            trace_type="segment",
            trace_id="t-seg",
            parent_trace_id="t-cycle",
            component="pipeline",
            fields={"duration_ms": "42"},
        )
        d = event.to_dict()
        assert d["event"] == "trace"
        assert d["trace_type"] == "segment"
        assert d["trace_id"] == "t-seg"
        assert d["parent_trace_id"] == "t-cycle"
        assert d["component"] == "pipeline"
        assert d["fields"] == {"duration_ms": "42"}
        assert "timestamp" in d

    def test_to_json_round_trippable(self):
        event = mod.TraceEvent(trace_type="job", trace_id="t-1")
        line = event.to_json()
        parsed = json.loads(line)
        assert parsed["event"] == "trace"
        assert parsed["trace_type"] == "job"
        assert parsed["trace_id"] == "t-1"

    def test_to_json_single_line(self):
        event = mod.TraceEvent(trace_type="job", trace_id="t-1")
        assert "\n" not in event.to_json()


# ------------------------------------------------------------------
# StdoutTraceSink
# ------------------------------------------------------------------


class TestStdoutTraceSink:
    def test_accept_writes_to_stderr(self, capsys):
        sink = mod.StdoutTraceSink()
        event = mod.TraceEvent(trace_type="job", trace_id="t-1")
        sink.accept(event)
        captured = capsys.readouterr()
        assert "t-1" in captured.err

    def test_accept_never_raises(self, capsys):
        sink = mod.StdoutTraceSink()
        sink.accept("bad")  # type: ignore[arg-type]
        # Should not raise


# ------------------------------------------------------------------
# CollectingTraceSink
# ------------------------------------------------------------------


class TestCollectingTraceSink:
    def test_collects_events(self):
        sink = mod.CollectingTraceSink()
        sink.accept(mod.TraceEvent(trace_type="job", trace_id="t-1"))
        sink.accept(mod.TraceEvent(trace_type="cycle", trace_id="t-2"))
        assert len(sink.events()) == 2

    def test_clear(self):
        sink = mod.CollectingTraceSink()
        sink.accept(mod.TraceEvent(trace_type="job", trace_id="t-1"))
        sink.clear()
        assert len(sink.events()) == 0

    def test_events_is_snapshot(self):
        sink = mod.CollectingTraceSink()
        sink.accept(mod.TraceEvent(trace_type="job", trace_id="t-1"))
        snap = sink.events()
        sink.accept(mod.TraceEvent(trace_type="job", trace_id="t-2"))
        assert len(snap) == 1


# ------------------------------------------------------------------
# emit_trace() — public API
# ------------------------------------------------------------------


class TestEmitTrace:
    def test_basic_emission(self):
        sink = mod.CollectingTraceSink()
        mod.clear_trace_sinks()
        mod.register_trace_sink(sink)
        try:
            with mod.TraceContext(correlation_id="c-1"):
                tid = mod.emit_trace(
                    "job",
                    component="test",
                    fields={"msg": "hello"},
                )
            assert len(sink.events()) == 1
            ev = sink.events()[0]
            assert ev.trace_type == "job"
            assert ev.trace_id == tid
            assert ev.correlation_id == "c-1"
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())

    def test_emit_with_parent(self):
        sink = mod.CollectingTraceSink()
        mod.clear_trace_sinks()
        mod.register_trace_sink(sink)
        try:
            mod.emit_trace(
                "cycle",
                parent_trace_id="t-parent",
                fields={"depth": "1"},
            )
            ev = sink.events()[0]
            assert ev.parent_trace_id == "t-parent"
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())

    def test_field_coercion(self):
        sink = mod.CollectingTraceSink()
        mod.clear_trace_sinks()
        mod.register_trace_sink(sink)
        try:
            mod.emit_trace(
                "segment",
                fields={"count": 42, "ok": True},
            )
            ev = sink.events()[0]
            assert ev.fields["count"] == "42"
            assert ev.fields["ok"] == "True"
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())

    def test_never_raises_on_bad_input(self):
        mod.clear_trace_sinks()
        try:
            mod.emit_trace(None)  # type: ignore[arg-type]
            mod.emit_trace("job", fields={"bad": object()})
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())

    def test_sink_failure_does_not_propagate(self):
        mod.clear_trace_sinks()
        try:

            class BrokenSink:
                def accept(self, event):
                    raise RuntimeError("boom")

            mod.register_trace_sink(BrokenSink())  # type: ignore[arg-type]
            mod.emit_trace("job", fields={"key": "val"})
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())

    def test_auto_trace_id_when_not_provided(self):
        sink = mod.CollectingTraceSink()
        mod.clear_trace_sinks()
        mod.register_trace_sink(sink)
        try:
            mod.emit_trace("cycle")
            ev = sink.events()[0]
            assert ev.trace_id != ""
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())


# ------------------------------------------------------------------
# TraceContext
# ------------------------------------------------------------------


class TestTraceContext:
    def test_sets_current_correlation(self):
        mod.clear_trace_sinks()
        try:
            with mod.TraceContext(correlation_id="c-1"):
                assert mod.current_correlation_id() == "c-1"
            assert mod.current_correlation_id() == ""
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())

    def test_nesting_restores_outer(self):
        mod.clear_trace_sinks()
        try:
            with mod.TraceContext(correlation_id="outer"):
                with mod.TraceContext(correlation_id="inner"):
                    assert mod.current_correlation_id() == "inner"
                assert mod.current_correlation_id() == "outer"
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())


# ------------------------------------------------------------------
# Stable root trace IDs
# ------------------------------------------------------------------


class TestRootTraceId:
    def test_same_correlation_returns_same_id(self):
        cid = "correlation-1"
        id1 = mod._root_trace_id(cid)
        id2 = mod._root_trace_id(cid)
        assert id1 == id2

    def test_different_correlations_different_ids(self):
        id1 = mod._root_trace_id("c-1")
        id2 = mod._root_trace_id("c-2")
        assert id1 != id2

    def test_empty_correlation_returns_empty(self):
        # Empty correlation_id returns empty string
        assert mod._root_trace_id("") == ""

    def test_returns_uuid_string(self):
        import uuid

        rid = mod._root_trace_id("test-cid")
        # Should be a valid UUID
        uuid.UUID(rid)


# ------------------------------------------------------------------
# Category helpers
# ------------------------------------------------------------------


class TestTraceCategoryHelpers:
    def test_emit_job_trace(self):
        sink = mod.CollectingTraceSink()
        mod.clear_trace_sinks()
        mod.register_trace_sink(sink)
        try:
            mod.emit_job_trace(
                "job-1", "pending", "queued", _correlation_id="c-1"
            )
            assert len(sink.events()) >= 1
            ev = sink.events()[0]
            assert ev.trace_type == "job"
            assert ev.correlation_id == "c-1"
            assert ev.fields.get("job_id") == "job-1"
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())

    def test_emit_cycle_trace(self):
        sink = mod.CollectingTraceSink()
        mod.clear_trace_sinks()
        mod.register_trace_sink(sink)
        try:
            mod.emit_cycle_trace(
                "job-1", "w-1", 1, "start",
                _correlation_id="c-1", parent_trace_id="t-root",
            )
            assert len(sink.events()) >= 1
            ev = sink.events()[0]
            assert ev.trace_type == "cycle"
            assert ev.fields.get("worker_id") == "w-1"
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())

    def test_emit_segment_trace(self):
        sink = mod.CollectingTraceSink()
        mod.clear_trace_sinks()
        mod.register_trace_sink(sink)
        try:
            mod.emit_segment_trace(
                "job-1", "pipeline", "start",
                _correlation_id="c-1", parent_trace_id="t-cycle",
            )
            assert len(sink.events()) >= 1
            ev = sink.events()[0]
            assert ev.trace_type == "segment"
            assert ev.fields.get("segment") == "pipeline"
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())


# ------------------------------------------------------------------
# Global sink registry
# ------------------------------------------------------------------


class TestTraceSinkRegistry:
    def test_register_and_clear(self):
        mod.clear_trace_sinks()
        try:
            sink = mod.CollectingTraceSink()
            mod.register_trace_sink(sink)
            assert len(mod._global_trace_sinks) == 1  # type: ignore[attr-defined]
            mod.clear_trace_sinks()
            assert len(mod._global_trace_sinks) == 0  # type: ignore[attr-defined]
        finally:
            mod.clear_trace_sinks()
            mod.register_trace_sink(mod.StdoutTraceSink())

    def test_default_sink_is_stdout(self):
        assert len(mod._global_trace_sinks) >= 1  # type: ignore[attr-defined]
        assert isinstance(mod._global_trace_sinks[-1], mod.StdoutTraceSink)  # type: ignore[attr-defined]
