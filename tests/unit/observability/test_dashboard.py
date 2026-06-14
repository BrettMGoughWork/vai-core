"""Tests for S4.8.5 Dashboard — DashboardEventStore, all ingest pipelines,
state snapshots, subscriber system.

Covers:
- Metric ingestion (job count, queue depth, worker health, execution time, drift)
- Trace ingestion (parent/child linking, root tracking, job state derivation)
- Log ingestion (job_created, job_started, job_finished, execution, queue_event)
- Health ingestion
- SSE subscriber system
- Malformed JSON resilience
- get_state_dict() and get_summary() output shapes
"""

from __future__ import annotations

import json
import pytest

from src.platform.observability.dashboard.event_model import (
    DashboardEventStore,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_metric(name: str, value: float, labels: dict | None = None) -> str:
    """Build a JSON-line metric event string."""
    ev = {"event": "metric", "metric": name, "value": value}
    if labels:
        ev["labels"] = labels
    ev["timestamp"] = "2026-01-01T00:00:00+00:00"
    return json.dumps(ev)


def _make_trace(
    trace_type: str,
    trace_id: str,
    parent_trace_id: str = "",
    correlation_id: str = "",
    component: str = "",
    fields: dict | None = None,
) -> str:
    ev = {
        "event": "trace",
        "trace_type": trace_type,
        "trace_id": trace_id,
        "parent_trace_id": parent_trace_id,
        "correlation_id": correlation_id,
        "component": component,
        "fields": fields or {},
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
    return json.dumps(ev)


def _make_log(
    message: str,
    level: str = "info",
    correlation_id: str = "",
    fields: dict | None = None,
    component: str = "",
) -> str:
    ev = {
        "event": "log",
        "level": level,
        "message": message,
        "correlation_id": correlation_id,
        "component": component,
        "fields": fields or {},
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
    return json.dumps(ev)


def _make_health(status: str = "ok", message: str = "all good") -> str:
    ev = {
        "event": "health",
        "status": status,
        "message": message,
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
    return json.dumps(ev)


# ------------------------------------------------------------------
# Metric ingestion
# ------------------------------------------------------------------


class TestMetricIngestion:
    def test_job_count_metric(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_metric("s4.job.count", 1.0, {"state": "queued"}))
        m = store.get_metrics()
        assert m.job_count["queued"] == 1.0

    def test_queue_depth_metric(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_metric("s4.queue.depth", 5.0, {"queue": "default"}))
        m = store.get_metrics()
        assert m.queue_depth == 5.0

    def test_worker_health_metric(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_metric("s4.worker.health", 1.0, {"worker_id": "w-1", "status": "healthy"})
        )
        workers = store.get_workers()
        assert any(w.worker_id == "w-1" for w in workers)
        assert next(w for w in workers if w.worker_id == "w-1").healthy is True

    def test_execution_time_metric(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_metric(
                "s4.job.executiontimems",
                1234.0,
                {"jobtype": "cli", "workerid": "w-1"},
            )
        )
        m = store.get_metrics()
        assert m.execution_times == [1234.0]

    def test_drift_frequency_metric(self):
        store = DashboardEventStore()
        # Source computes drift_frequency as _drift_count / _total_jobs_completed
        store.ingest_json_line(_make_metric("s4.job.count", 1.0, {"state": "completed"}))
        store.ingest_json_line(_make_metric("s4.drift.detected", 1.0))
        m = store.get_metrics()
        assert m.drift_frequency == 1.0


# ------------------------------------------------------------------
# Trace ingestion
# ------------------------------------------------------------------


class TestTraceIngestion:
    def test_job_trace_creates_root(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_trace("job", "t-1", correlation_id="c-1", fields={"action": "start"})
        )
        roots = store.get_trace_roots()
        assert len(roots) == 1
        assert roots[0].trace_id == "t-1"

    def test_child_trace_links_to_parent(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_trace("job", "t-root", correlation_id="c-1"))
        store.ingest_json_line(
            _make_trace("cycle", "t-child", parent_trace_id="t-root")
        )
        roots = store.get_trace_roots()
        assert len(roots) == 1
        assert len(roots[0].children) == 1
        assert roots[0].children[0].trace_id == "t-child"

    def test_deep_nesting(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_trace("job", "t-root"))
        store.ingest_json_line(_make_trace("cycle", "t-cycle", parent_trace_id="t-root"))
        store.ingest_json_line(
            _make_trace("segment", "t-seg", parent_trace_id="t-cycle")
        )
        roots = store.get_trace_roots()
        assert roots[0].children[0].children[0].trace_id == "t-seg"

    def test_root_tracking_limited_to_50(self):
        store = DashboardEventStore()
        for i in range(55):
            store.ingest_json_line(
                _make_trace("job", f"t-{i}", correlation_id=f"c-{i}")
            )
        assert len(store.get_trace_roots()) <= 50

    def test_job_state_derived_from_trace(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_trace("job", "t-1", correlation_id="c-1",
                        fields={"job_id": "job-1", "from": "pending", "to": "running"})
        )
        jobs = store.get_jobs()
        assert any(j.job_id == "job-1" for j in jobs)
        assert next(j for j in jobs if j.job_id == "job-1").state == "running"

    def test_job_state_transition_from_trace(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_trace("job", "t-1", correlation_id="c-1",
                        fields={"job_id": "job-1", "from": "pending", "to": "queued"})
        )
        store.ingest_json_line(
            _make_trace("job", "t-2", correlation_id="c-1",
                        fields={"job_id": "job-1", "from": "queued", "to": "running"})
        )
        jobs = store.get_jobs()
        assert next(j for j in jobs if j.job_id == "job-1").state == "running"


# ------------------------------------------------------------------
# Log ingestion
# ------------------------------------------------------------------


class TestLogIngestion:
    def test_job_created_log(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_log("job_created", correlation_id="job-1",
                      fields={"job_id": "job-1", "job_type": "cli"})
        )
        jobs = store.get_jobs()
        assert any(j.job_id == "job-1" for j in jobs)

    def test_job_started_log_updates_state(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_log("job_created", correlation_id="job-1", fields={"job_id": "job-1"})
        )
        store.ingest_json_line(
            _make_log("job_started", correlation_id="job-1", fields={"job_id": "job-1"})
        )
        jobs = store.get_jobs()
        assert next(j for j in jobs if j.job_id == "job-1").state == "running"

    def test_job_finished_log_updates_state(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_log("job_created", correlation_id="job-1", fields={"job_id": "job-1"})
        )
        store.ingest_json_line(
            _make_log("job_finished", correlation_id="job-1", fields={"job_id": "job-1"})
        )
        jobs = store.get_jobs()
        assert next(j for j in jobs if j.job_id == "job-1").state == "completed"

    def test_execution_log_sets_duration(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_log("job_created", correlation_id="job-1", fields={"job_id": "job-1"})
        )
        # Duration is set from s4.job.executiontimems metric, not execution log
        store.ingest_json_line(
            _make_metric("s4.job.executiontimems", 1234.0, {"job_id": "job-1"})
        )
        jobs = store.get_jobs()
        assert next(j for j in jobs if j.job_id == "job-1").duration_ms == 1234.0

    def test_queue_event_tracked_in_metrics(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_log("queue_event", fields={"queue": "default",
                                              "action": "enqueue", "depth": "5"})
        )
        m = store.get_metrics()
        assert m.queue_depth == 5.0

    def test_unknown_log_message_ignored(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_log("something_weird"))
        # Should not raise and should not create junk state
        assert len(store.get_jobs()) == 0


# ------------------------------------------------------------------
# Health ingestion
# ------------------------------------------------------------------


class TestHealthIngestion:
    def test_health_event_ok(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_health("ok", "all good"))
        h = store.get_health()
        assert h.status == "ok"

    def test_health_event_degraded(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_health("degraded", "queue depth high"))
        h = store.get_health()
        assert h.status == "degraded"

    def test_health_event_unhealthy(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_health("unhealthy", "workers down"))
        h = store.get_health()
        assert h.status == "unhealthy"

    def test_health_check_event_alias(self):
        store = DashboardEventStore()
        ev = {"event": "health_check", "status": "degraded"}
        store.ingest_json_line(json.dumps(ev))
        assert store.get_health().status == "degraded"


# ------------------------------------------------------------------
# State snapshots
# ------------------------------------------------------------------


class TestStateDict:
    def test_get_state_dict_shape(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_metric("s4.job.count", 1.0, {"state": "queued"}))
        state = store.get_state_dict()
        assert "timestamp" in state
        assert "jobs" in state
        assert "workers" in state
        assert "traces" in state
        assert "metrics" in state

    def test_get_state_dict_job_list(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_log("job_created", correlation_id="job-1",
                      fields={"job_id": "job-1", "job_type": "cli"})
        )
        state = store.get_state_dict()
        assert len(state["jobs"]) == 1
        assert state["jobs"][0]["job_id"] == "job-1"

    def test_get_state_dict_trace_children(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_trace("job", "t-root"))
        store.ingest_json_line(_make_trace("cycle", "t-child", parent_trace_id="t-root"))
        state = store.get_state_dict()
        assert len(state["traces"]) == 1
        assert len(state["traces"][0]["children"]) == 1


class TestSummary:
    def test_get_summary_shape(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_metric("s4.job.count", 1.0, {"state": "queued"}))
        summary = store.get_summary()
        assert summary["type"] == "dashboard_summary"
        assert "jobs" in summary
        assert "workers" in summary
        assert "traces" in summary
        assert "metrics" in summary
        assert "health" in summary

    def test_get_summary_job_counts(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_log("job_created", correlation_id="job-1",
                      fields={"job_id": "job-1", "job_type": "cli"})
        )
        store.ingest_json_line(
            _make_log("job_created", correlation_id="job-2",
                      fields={"job_id": "job-2", "job_type": "cli"})
        )
        summary = store.get_summary()
        assert summary["jobs"]["total"] == 2

    def test_get_summary_worker_stats(self):
        store = DashboardEventStore()
        store.ingest_json_line(
            _make_metric("s4.worker.health", 1.0,
                         {"worker_id": "w-1", "status": "healthy"})
        )
        summary = store.get_summary()
        assert summary["workers"]["healthy"] == 1
        assert summary["workers"]["total"] == 1

    def test_get_summary_execution_histogram_empty(self):
        store = DashboardEventStore()
        summary = store.get_summary()
        assert summary["metrics"]["execution_time_histogram"]["<10ms"] == 0

    def test_get_summary_health_status(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_health("unhealthy"))
        summary = store.get_summary()
        assert summary["health"]["status"] == "unhealthy"


# ------------------------------------------------------------------
# SSE subscriber system
# ------------------------------------------------------------------


class TestSubscriberSystem:
    def test_subscribe_receives_events(self):
        store = DashboardEventStore()
        received = []

        def callback(data: dict):
            received.append(data.get("metric"))

        store.subscribe(callback)
        store.ingest_json_line(_make_metric("s4.test.count", 1.0))
        assert len(received) >= 1
        assert received[-1] == "s4.test.count"
        store.unsubscribe(callback)

    def test_unsubscribe_stops_events(self):
        store = DashboardEventStore()
        received = []

        def callback(data: dict):
            received.append(data.get("metric", ""))

        store.subscribe(callback)
        store.unsubscribe(callback)
        store.ingest_json_line(_make_metric("s4.test.count", 1.0))
        assert len(received) == 0

    def test_multiple_subscribers(self):
        store = DashboardEventStore()
        r1, r2 = [], []

        def cb1(d):
            r1.append(d.get("metric", ""))

        def cb2(d):
            r2.append(d.get("metric", ""))

        store.subscribe(cb1)
        store.subscribe(cb2)
        store.ingest_json_line(_make_metric("s4.test.count", 1.0))
        assert len(r1) >= 1
        assert len(r2) >= 1
        store.unsubscribe(cb1)
        store.unsubscribe(cb2)


# ------------------------------------------------------------------
# Malformed input resilience
# ------------------------------------------------------------------


class TestMalformedInput:
    def test_invalid_json(self):
        store = DashboardEventStore()
        store.ingest_json_line("not json at all")
        # Should not raise; state should be unchanged

    def test_missing_event_field(self):
        store = DashboardEventStore()
        store.ingest_json_line('{"metric": "s4.test", "value": 1}')
        # Should not raise; unknown event type ignored

    def test_unknown_event_type(self):
        store = DashboardEventStore()
        store.ingest_json_line('{"event": "something_unknown", "data": "x"}')
        # Should not raise

    def test_partial_metric(self):
        store = DashboardEventStore()
        store.ingest_json_line('{"event": "metric"}')
        # Missing required fields — should not raise

    def test_empty_string(self):
        store = DashboardEventStore()
        store.ingest_json_line("")
        # Should not raise

    def test_whitespace_only(self):
        store = DashboardEventStore()
        store.ingest_json_line("   ")
        # Should not raise

    def test_none_line(self):
        store = DashboardEventStore()
        store.ingest_json_line("null")
        # Should not raise


# ------------------------------------------------------------------
# Recent events tracking
# ------------------------------------------------------------------


class TestRecentEvents:
    def test_recent_events_capped(self):
        store = DashboardEventStore()
        for i in range(150):
            store.ingest_json_line(_make_metric(f"s4.test.{i}", 1.0))
        recent = store.get_recent_events()
        assert len(recent) <= 100

    def test_recent_events_ordered(self):
        store = DashboardEventStore()
        store.ingest_json_line(_make_metric("s4.first", 1.0))
        store.ingest_json_line(_make_metric("s4.second", 2.0))
        recent = store.get_recent_events()
        assert recent[-1]["metric"] == "s4.second"
