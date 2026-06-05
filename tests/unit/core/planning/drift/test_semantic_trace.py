"""
Tests for Phase 2.8.5 — Semantic Trace.

Covers:
  - SemanticTrace dataclass validation
  - build_semantic_trace() pure function
  - Mismatch summaries captured correctly
  - Repair actions captured correctly
  - Drift history appended correctly
  - No mutation of inputs
  - Deterministic output
  - JSON safety
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from src.core.planning.drift.segment_trace_types import SemanticTrace
from src.core.planning.drift.semantic_signal_types import (
    SemanticDriftClassification,
    SemanticDriftSignal,
    SemanticMismatch,
    SemanticRepairPlan,
)
from src.core.planning.drift.semantic_trace import (
    _build_classification_summary,
    _build_drift_history,
    _build_mismatch_summaries,
    build_semantic_trace,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _mismatch(
    mtype: str,
    confidence: float = 0.7,
    details: Dict[str, Any] | None = None,
) -> SemanticMismatch:
    return SemanticMismatch(
        type=mtype,  # type: ignore[arg-type]
        confidence=confidence,
        details=details or {},
    )


def _drift_signal(
    stype: str,
    confidence: float = 0.7,
    details: Dict[str, Any] | None = None,
) -> SemanticDriftSignal:
    return SemanticDriftSignal(
        type=stype,  # type: ignore[arg-type]
        confidence=confidence,
        details=details or {},
    )


def _classification(
    status: str = "no_drift",
    categories: List[str] | None = None,
    confidence: float = 0.0,
    reasons: List[SemanticDriftSignal] | None = None,
    streak: int = 0,
) -> SemanticDriftClassification:
    return SemanticDriftClassification(
        status=status,  # type: ignore[arg-type]
        categories=categories or [],
        confidence=confidence,
        reasons=reasons or [],
        streak=streak,
    )


def _repair(
    needs_repair: bool = False,
    repair_actions: List[str] | None = None,
    confidence: float = 0.0,
    categories: List[str] | None = None,
    streak: int = 0,
) -> SemanticRepairPlan:
    return SemanticRepairPlan(
        needs_repair=needs_repair,
        repair_actions=repair_actions or [],
        confidence=confidence,
        categories=categories or [],
        streak=streak,
    )


def _trace(
    mismatches: List[Dict[str, Any]] | None = None,
    actions: List[str] | None = None,
    history: List[Dict[str, Any]] | None = None,
) -> SemanticTrace:
    return SemanticTrace(
        semantic_mismatches=mismatches or [],
        semantic_repair_actions=actions or [],
        semantic_drift_history=history or [],
    )


# ============================================================================
# SemanticTrace dataclass
# ============================================================================


class TestSemanticTrace:
    """Tests for the SemanticTrace frozen dataclass."""

    def test_empty_trace_construction(self) -> None:
        trace = SemanticTrace(
            semantic_mismatches=[],
            semantic_repair_actions=[],
            semantic_drift_history=[],
        )
        assert trace.semantic_mismatches == []
        assert trace.semantic_repair_actions == []
        assert trace.semantic_drift_history == []

    def test_full_trace_construction(self) -> None:
        mismatches = [
            {"type": "step_mismatch", "confidence": 0.7, "details": {"reason": "X"}},
        ]
        actions = ["rewrite plan"]
        history = [
            {"status": "semantic_drift", "categories": ["contradictplan"],
             "confidence": 0.8, "streak": 1},
        ]
        trace = SemanticTrace(
            semantic_mismatches=mismatches,
            semantic_repair_actions=actions,
            semantic_drift_history=history,
        )
        assert trace.semantic_mismatches == mismatches
        assert trace.semantic_repair_actions == actions
        assert trace.semantic_drift_history == history

    def test_frozen(self) -> None:
        trace = SemanticTrace(
            semantic_mismatches=[],
            semantic_repair_actions=[],
            semantic_drift_history=[],
        )
        with pytest.raises(Exception):
            trace.semantic_repair_actions = ["mutated"]  # type: ignore[misc]

    def test_mismatches_defensive_copy(self) -> None:
        mismatches = [{"type": "step_mismatch", "confidence": 0.7, "details": {}}]
        trace = SemanticTrace(
            semantic_mismatches=mismatches,
            semantic_repair_actions=[],
            semantic_drift_history=[],
        )
        mismatches.append({"type": "plan_mismatch", "confidence": 0.8, "details": {}})
        assert len(trace.semantic_mismatches) == 1

    def test_repair_actions_defensive_copy(self) -> None:
        actions = ["rewrite plan"]
        trace = SemanticTrace(
            semantic_mismatches=[],
            semantic_repair_actions=actions,
            semantic_drift_history=[],
        )
        actions.append("rewrite step")
        assert trace.semantic_repair_actions == ["rewrite plan"]

    def test_drift_history_defensive_copy(self) -> None:
        history = [{"status": "no_drift", "categories": [], "confidence": 0.0, "streak": 0}]
        trace = SemanticTrace(
            semantic_mismatches=[],
            semantic_repair_actions=[],
            semantic_drift_history=history,
        )
        history.append({"status": "semantic_drift", "categories": [], "confidence": 1.0, "streak": 1})
        assert len(trace.semantic_drift_history) == 1


# ============================================================================
# _build_mismatch_summaries
# ============================================================================


class TestBuildMismatchSummaries:
    """Tests for converting mismatches to JSON‑safe summaries."""

    def test_empty_mismatches(self) -> None:
        assert _build_mismatch_summaries([]) == []

    def test_single_mismatch(self) -> None:
        m = _mismatch("step_mismatch", confidence=0.7, details={"reason": "X"})
        summaries = _build_mismatch_summaries([m])
        assert summaries == [
            {"type": "step_mismatch", "confidence": 0.7, "details": {"reason": "X"}},
        ]

    def test_sorted_by_type(self) -> None:
        m1 = _mismatch("plan_mismatch", confidence=0.8, details={"reason": "Y"})
        m2 = _mismatch("step_mismatch", confidence=0.7, details={"reason": "X"})
        m3 = _mismatch("memory_mismatch", confidence=0.6, details={"reason": "Z"})
        summaries = _build_mismatch_summaries([m1, m2, m3])
        types = [s["type"] for s in summaries]
        assert types == ["memory_mismatch", "plan_mismatch", "step_mismatch"]

    def test_all_four_types(self) -> None:
        mismatches = [
            _mismatch("plan_mismatch", confidence=0.8),
            _mismatch("subgoal_mismatch", confidence=0.9),
            _mismatch("step_mismatch", confidence=0.7),
            _mismatch("memory_mismatch", confidence=0.6),
        ]
        summaries = _build_mismatch_summaries(mismatches)
        types = [s["type"] for s in summaries]
        assert types == [
            "memory_mismatch", "plan_mismatch", "step_mismatch", "subgoal_mismatch",
        ]

    def test_details_deep_copied(self) -> None:
        details = {"reason": "X"}
        m = _mismatch("step_mismatch", details=details)
        summaries = _build_mismatch_summaries([m])
        details["reason"] = "Y"
        assert summaries[0]["details"] == {"reason": "X"}

    def test_confidence_preserved(self) -> None:
        m = _mismatch("plan_mismatch", confidence=0.85)
        summaries = _build_mismatch_summaries([m])
        assert summaries[0]["confidence"] == 0.85


# ============================================================================
# _build_classification_summary
# ============================================================================


class TestBuildClassificationSummary:
    """Tests for converting a classification to a JSON‑safe summary."""

    def test_no_drift_summary(self) -> None:
        clf = _classification(status="no_drift", confidence=0.0, streak=0)
        summary = _build_classification_summary(clf)
        assert summary == {
            "status": "no_drift",
            "categories": [],
            "confidence": 0.0,
            "streak": 0,
        }

    def test_semantic_drift_summary(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan", "contradictsubgoal"],
            confidence=0.9,
            streak=3,
        )
        summary = _build_classification_summary(clf)
        assert summary == {
            "status": "semantic_drift",
            "categories": ["contradictplan", "contradictsubgoal"],
            "confidence": 0.9,
            "streak": 3,
        }

    def test_categories_is_defensive_copy(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.8,
            streak=1,
        )
        summary = _build_classification_summary(clf)
        summary["categories"].append("contradictsubgoal")
        assert clf.categories == ["contradictplan"]


# ============================================================================
# _build_drift_history
# ============================================================================


class TestBuildDriftHistory:
    """Tests for building the semantic drift history list."""

    def test_no_previous_trace(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.8,
            streak=1,
        )
        history = _build_drift_history(clf, None)
        assert len(history) == 1
        assert history[0]["status"] == "semantic_drift"
        assert history[0]["categories"] == ["contradictplan"]
        assert history[0]["confidence"] == 0.8
        assert history[0]["streak"] == 1

    def test_appends_to_previous_history(self) -> None:
        prev_trace = _trace(
            history=[
                {"status": "no_drift", "categories": [], "confidence": 0.0, "streak": 0},
            ],
        )
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.8,
            streak=1,
        )
        history = _build_drift_history(clf, prev_trace)
        assert len(history) == 2
        assert history[0]["status"] == "no_drift"
        assert history[1]["status"] == "semantic_drift"

    def test_does_not_mutate_previous_trace(self) -> None:
        prev_trace = _trace(
            history=[
                {"status": "no_drift", "categories": [], "confidence": 0.0, "streak": 0},
            ],
        )
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.8,
            streak=1,
        )
        _build_drift_history(clf, prev_trace)
        assert len(prev_trace.semantic_drift_history) == 1

    def test_multiple_cycles(self) -> None:
        clf1 = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.8,
            streak=1,
        )
        clf2 = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.9,
            streak=2,
        )
        history1 = _build_drift_history(clf1, None)
        trace1 = _trace(history=history1)
        history2 = _build_drift_history(clf2, trace1)
        assert len(history2) == 2
        assert history2[0]["streak"] == 1
        assert history2[1]["streak"] == 2


# ============================================================================
# build_semantic_trace — core logic
# ============================================================================


class TestBuildSemanticTrace:
    """Tests for the build_semantic_trace() pure function."""

    # ── semantic mismatches ───────────────────────────────────────────────

    def test_mismatches_captured(self) -> None:
        mismatches = [
            _mismatch("step_mismatch", confidence=0.7, details={"reason": "X"}),
            _mismatch("plan_mismatch", confidence=0.8, details={"reason": "Y"}),
        ]
        trace = build_semantic_trace(
            mismatches=mismatches,
            drift_signals=[],
            classification=_classification(),
            repair_plan=_repair(),
        )
        types = [m["type"] for m in trace.semantic_mismatches]
        assert types == ["plan_mismatch", "step_mismatch"]

    def test_no_mismatches_empty_list(self) -> None:
        trace = build_semantic_trace(
            mismatches=[],
            drift_signals=[],
            classification=_classification(),
            repair_plan=_repair(),
        )
        assert trace.semantic_mismatches == []

    # ── semantic repair actions ───────────────────────────────────────────

    def test_repair_actions_captured(self) -> None:
        trace = build_semantic_trace(
            mismatches=[],
            drift_signals=[],
            classification=_classification(),
            repair_plan=_repair(repair_actions=["rewrite plan", "rewrite subgoal"]),
        )
        assert trace.semantic_repair_actions == ["rewrite plan", "rewrite subgoal"]

    def test_repair_actions_sorted(self) -> None:
        trace = build_semantic_trace(
            mismatches=[],
            drift_signals=[],
            classification=_classification(),
            repair_plan=_repair(
                repair_actions=["rewrite subgoal", "rewrite step", "rewrite plan"],
            ),
        )
        assert trace.semantic_repair_actions == [
            "rewrite plan", "rewrite step", "rewrite subgoal",
        ]

    def test_no_repair_actions_empty_list(self) -> None:
        trace = build_semantic_trace(
            mismatches=[],
            drift_signals=[],
            classification=_classification(),
            repair_plan=_repair(),
        )
        assert trace.semantic_repair_actions == []

    # ── semantic drift history ────────────────────────────────────────────

    def test_drift_history_first_cycle(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.8,
            streak=1,
        )
        trace = build_semantic_trace(
            mismatches=[],
            drift_signals=[],
            classification=clf,
            repair_plan=_repair(),
            previous_trace=None,
        )
        assert len(trace.semantic_drift_history) == 1
        assert trace.semantic_drift_history[0]["status"] == "semantic_drift"

    def test_drift_history_appends(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.9,
            streak=2,
        )
        prev = _trace(
            history=[
                {"status": "no_drift", "categories": [], "confidence": 0.0, "streak": 0},
            ],
        )
        trace = build_semantic_trace(
            mismatches=[],
            drift_signals=[],
            classification=clf,
            repair_plan=_repair(),
            previous_trace=prev,
        )
        assert len(trace.semantic_drift_history) == 2

    def test_no_drift_history(self) -> None:
        trace = build_semantic_trace(
            mismatches=[],
            drift_signals=[],
            classification=_classification(status="no_drift"),
            repair_plan=_repair(),
            previous_trace=None,
        )
        assert len(trace.semantic_drift_history) == 1
        assert trace.semantic_drift_history[0]["status"] == "no_drift"

    # ── determinism ───────────────────────────────────────────────────────

    def test_deterministic_output(self) -> None:
        mismatches = [_mismatch("plan_mismatch", confidence=0.8)]
        classification = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.8,
            streak=1,
        )
        repair_plan = _repair(repair_actions=["rewrite plan"])

        t1 = build_semantic_trace(
            mismatches=mismatches,
            drift_signals=[],
            classification=classification,
            repair_plan=repair_plan,
        )
        t2 = build_semantic_trace(
            mismatches=mismatches,
            drift_signals=[],
            classification=classification,
            repair_plan=repair_plan,
        )
        assert t1.semantic_mismatches == t2.semantic_mismatches
        assert t1.semantic_repair_actions == t2.semantic_repair_actions
        assert t1.semantic_drift_history == t2.semantic_drift_history

    # ── non‑mutation invariants ───────────────────────────────────────────

    def test_does_not_mutate_mismatches(self) -> None:
        mismatches = [_mismatch("step_mismatch", confidence=0.7, details={"reason": "X"})]
        build_semantic_trace(
            mismatches=mismatches,
            drift_signals=[],
            classification=_classification(),
            repair_plan=_repair(),
        )
        assert mismatches[0].type == "step_mismatch"
        assert mismatches[0].details == {"reason": "X"}

    def test_does_not_mutate_classification(self) -> None:
        clf = _classification(
            status="semantic_drift",
            categories=["contradictplan"],
            confidence=0.8,
            streak=1,
        )
        build_semantic_trace(
            mismatches=[],
            drift_signals=[],
            classification=clf,
            repair_plan=_repair(),
        )
        assert clf.status == "semantic_drift"
        assert clf.categories == ["contradictplan"]

    def test_does_not_mutate_repair_plan(self) -> None:
        rp = _repair(repair_actions=["rewrite plan"])
        build_semantic_trace(
            mismatches=[],
            drift_signals=[],
            classification=_classification(),
            repair_plan=rp,
        )
        assert rp.repair_actions == ["rewrite plan"]

    def test_does_not_mutate_drift_signals(self) -> None:
        signals = [_drift_signal("contradictplan", details={"x": 1})]
        build_semantic_trace(
            mismatches=[],
            drift_signals=signals,
            classification=_classification(),
            repair_plan=_repair(),
        )
        assert signals[0].type == "contradictplan"
        assert signals[0].details == {"x": 1}

    # ── JSON safety ───────────────────────────────────────────────────────

    def test_result_is_json_safe(self) -> None:
        trace = build_semantic_trace(
            mismatches=[
                _mismatch("plan_mismatch", confidence=0.8, details={"reason": "Y"}),
            ],
            drift_signals=[],
            classification=_classification(
                status="semantic_drift",
                categories=["contradictplan"],
                confidence=0.8,
                streak=1,
            ),
            repair_plan=_repair(
                needs_repair=True,
                repair_actions=["rewrite plan"],
            ),
        )
        dumped = json.dumps({
            "semantic_mismatches": trace.semantic_mismatches,
            "semantic_repair_actions": trace.semantic_repair_actions,
            "semantic_drift_history": trace.semantic_drift_history,
        })
        assert isinstance(dumped, str)
        loaded = json.loads(dumped)
        assert loaded["semantic_mismatches"] == trace.semantic_mismatches
        assert loaded["semantic_repair_actions"] == trace.semantic_repair_actions
        assert loaded["semantic_drift_history"] == trace.semantic_drift_history

    # ── full integration ──────────────────────────────────────────────────

    def test_full_integration(self) -> None:
        mismatches = [
            _mismatch("step_mismatch", confidence=0.7, details={"reason": "X"}),
            _mismatch("plan_mismatch", confidence=0.8, details={"reason": "Y"}),
        ]
        classification = _classification(
            status="semantic_drift",
            categories=["contradictplan", "contradictprior_behaviour"],
            confidence=0.9,
            streak=2,
        )
        repair_plan = _repair(
            needs_repair=True,
            repair_actions=["rewrite plan", "rewrite step"],
        )
        prev_trace = _trace(
            history=[
                {"status": "no_drift", "categories": [], "confidence": 0.0, "streak": 0},
            ],
        )

        trace = build_semantic_trace(
            mismatches=mismatches,
            drift_signals=[],
            classification=classification,
            repair_plan=repair_plan,
            previous_trace=prev_trace,
        )

        # Mismatch summaries sorted
        assert [m["type"] for m in trace.semantic_mismatches] == [
            "plan_mismatch", "step_mismatch",
        ]
        # Repair actions sorted
        assert trace.semantic_repair_actions == ["rewrite plan", "rewrite step"]
        # History appended
        assert len(trace.semantic_drift_history) == 2
        assert trace.semantic_drift_history[1]["status"] == "semantic_drift"
        assert trace.semantic_drift_history[1]["streak"] == 2
