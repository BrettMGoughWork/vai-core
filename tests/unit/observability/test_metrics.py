"""Tests for S4.8.1 Metrics — MetricEvent, sinks, emit_metric(), global registry.

Covers:
- MetricEvent construction, to_dict(), to_json()
- StdoutSink and CollectingSink behaviour
- emit_metric() basic emission and label coercion
- register_sink / clear_sinks global registry
- Exception hardening (never raises)
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from src.platform.observability import metrics as mod


# ------------------------------------------------------------------
# MetricEvent
# ------------------------------------------------------------------


class TestMetricEvent:
    def test_construct_defaults(self):
        event = mod.MetricEvent(name="s4.test.count", value=1.0)
        assert event.name == "s4.test.count"
        assert event.value == 1.0
        assert event.labels == {}
        assert isinstance(event.timestamp, str)

    def test_construct_with_labels(self):
        event = mod.MetricEvent(
            name="s4.job.count",
            value=1,
            labels={"state": "queued"},
        )
        assert event.labels == {"state": "queued"}

    def test_to_dict_shape(self):
        event = mod.MetricEvent(name="s4.test", value=42.0, labels={"a": "b"})
        d = event.to_dict()
        assert d["event"] == "metric"
        assert d["metric"] == "s4.test"
        assert d["value"] == 42.0
        assert d["labels"] == {"a": "b"}
        assert "timestamp" in d

    def test_to_json_round_trippable(self):
        event = mod.MetricEvent(name="s4.test", value=3.14, labels={"k": "v"})
        line = event.to_json()
        parsed = json.loads(line)
        assert parsed["event"] == "metric"
        assert parsed["metric"] == "s4.test"
        assert parsed["value"] == 3.14

    def test_to_json_is_single_line(self):
        event = mod.MetricEvent(name="s4.test", value=1.0)
        line = event.to_json()
        assert "\n" not in line


# ------------------------------------------------------------------
# StdoutSink
# ------------------------------------------------------------------


class TestStdoutSink:
    def test_accept_writes_to_stdout(self, capsys):
        sink = mod.StdoutSink()
        event = mod.MetricEvent(name="s4.test", value=1.0)
        sink.accept(event)
        captured = capsys.readouterr()
        assert "s4.test" in captured.out

    def test_accept_never_raises(self, capsys):
        sink = mod.StdoutSink()
        # Inject a broken event by calling accept with a malformed type;
        # StdoutSink wraps write in try/except.
        sink.accept("not an event")  # type: ignore[arg-type]
        # Should not raise


# ------------------------------------------------------------------
# CollectingSink
# ------------------------------------------------------------------


class TestCollectingSink:
    def test_collects_events(self):
        sink = mod.CollectingSink()
        sink.accept(mod.MetricEvent(name="s4.a", value=1.0))
        sink.accept(mod.MetricEvent(name="s4.b", value=2.0))
        assert len(sink.events()) == 2

    def test_clear_discards(self):
        sink = mod.CollectingSink()
        sink.accept(mod.MetricEvent(name="s4.a", value=1.0))
        sink.clear()
        assert len(sink.events()) == 0

    def test_events_returns_snapshot(self):
        sink = mod.CollectingSink()
        sink.accept(mod.MetricEvent(name="s4.a", value=1.0))
        snap = sink.events()
        sink.accept(mod.MetricEvent(name="s4.b", value=2.0))
        # Snapshot should reflect state at time of call
        assert len(snap) == 1

    def test_accept_thread_safe(self):
        import threading

        sink = mod.CollectingSink()
        barrier = threading.Barrier(4)

        def _emit():
            barrier.wait()
            for _ in range(100):
                sink.accept(mod.MetricEvent(name="s4.t", value=1.0))

        threads = [threading.Thread(target=_emit) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(sink.events()) == 400


# ------------------------------------------------------------------
# emit_metric() — public API
# ------------------------------------------------------------------


class TestEmitMetric:
    def test_basic_emission(self):
        sink = mod.CollectingSink()
        mod.clear_sinks()
        mod.register_sink(sink)
        try:
            mod.emit_metric("s4.test.count", 1.0, {"state": "ok"})
            assert len(sink.events()) == 1
            ev = sink.events()[0]
            assert ev.name == "s4.test.count"
            assert ev.labels == {"state": "ok"}
        finally:
            mod.clear_sinks()
            mod.register_sink(mod.StdoutSink())

    def test_emission_without_labels(self):
        sink = mod.CollectingSink()
        mod.clear_sinks()
        mod.register_sink(sink)
        try:
            mod.emit_metric("s4.test.count", 42)
            assert len(sink.events()) == 1
            assert sink.events()[0].value == 42.0
        finally:
            mod.clear_sinks()
            mod.register_sink(mod.StdoutSink())

    def test_label_coercion(self):
        sink = mod.CollectingSink()
        mod.clear_sinks()
        mod.register_sink(sink)
        try:
            mod.emit_metric("s4.test", 1.0, {"count": 99, "flag": True})
            ev = sink.events()[0]
            # Values should be coerced to str
            assert ev.labels["count"] == "99"
            assert ev.labels["flag"] == "True"
        finally:
            mod.clear_sinks()
            mod.register_sink(mod.StdoutSink())

    def test_never_raises_on_bad_name(self):
        mod.clear_sinks()
        try:
            # Should not raise
            mod.emit_metric(None, "bad")  # type: ignore[arg-type]
            mod.emit_metric("s4.test", {})  # type: ignore[arg-type]
        finally:
            mod.clear_sinks()
            mod.register_sink(mod.StdoutSink())

    def test_sink_failure_during_emit_does_not_propagate(self):
        mod.clear_sinks()
        try:

            class BrokenSink:
                def accept(self, event):
                    raise RuntimeError("boom")

            mod.register_sink(BrokenSink())  # type: ignore[arg-type]
            # Should not raise despite broken sink
            mod.emit_metric("s4.test", 1.0)
        finally:
            mod.clear_sinks()
            mod.register_sink(mod.StdoutSink())


# ------------------------------------------------------------------
# Global sink registry
# ------------------------------------------------------------------


class TestSinkRegistry:
    def test_register_and_clear(self):
        mod.clear_sinks()
        try:
            sink = mod.CollectingSink()
            assert len(mod._global_sinks) == 0  # type: ignore[attr-defined]
            mod.register_sink(sink)
            assert len(mod._global_sinks) == 1  # type: ignore[attr-defined]
            mod.clear_sinks()
            assert len(mod._global_sinks) == 0  # type: ignore[attr-defined]
        finally:
            mod.clear_sinks()
            mod.register_sink(mod.StdoutSink())

    def test_register_twice_delivers_to_both(self):
        s1, s2 = mod.CollectingSink(), mod.CollectingSink()
        mod.clear_sinks()
        try:
            mod.register_sink(s1)
            mod.register_sink(s2)
            mod.emit_metric("s4.test", 1.0)
            assert len(s1.events()) == 1
            assert len(s2.events()) == 1
        finally:
            mod.clear_sinks()
            mod.register_sink(mod.StdoutSink())

    def test_default_sink_is_stdout(self):
        assert len(mod._global_sinks) >= 1  # type: ignore[attr-defined]
        assert isinstance(mod._global_sinks[-1], mod.StdoutSink)  # type: ignore[attr-defined]
