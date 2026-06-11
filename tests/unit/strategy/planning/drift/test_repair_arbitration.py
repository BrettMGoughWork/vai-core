"""
Tests for Phase 2.10.3 — Repair Arbitration Engine
===================================================

Covers ``decide_arbitration_action()`` and all helper functions with:

- Catastrophic drift → "catastrophic" immediately
- Budget exhaustion overrides for each scope
- Severity rules (minor → repair, major → regen_segment)
- Category rules (structural → repair, behavioural → regen_segment, etc.)
- Confidence tier rules (low → repair, medium → unchanged, high → escalate)
- Minimality principle
- Deterministic output
- JSON‑safe
- No mutation of inputs
- Individual choose_* helpers
"""
from __future__ import annotations

import json

import pytest

from src.strategy.planning.drift.unified_drift_types import (
    UnifiedDriftClassification,
    UnifiedDriftSignal,
)
from src.strategy.planning.drift.repair_budget import (
    RepairBudgetConfig,
    RepairBudgetState,
    apply_repair_budget,
)
from src.strategy.planning.drift.repair_arbitration import (
    ArbitrationDecision,
    decide_arbitration_action,
    choose_repair,
    choose_replan,
    choose_regen_segment,
    choose_regen_subgoal,
    choose_catastrophic,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_signal(
    source: str = "structural",
    type_: str = "shape_mismatch",
    weight: float = 0.5,
    decay: float = 1.0,
    confidence: float = 0.5,
) -> UnifiedDriftSignal:
    return UnifiedDriftSignal(
        source=source,
        type=type_,
        weight=weight,
        decay=decay,
        confidence=confidence,
        details={"test": True},
    )


def _make_classification(
    severity: str = "minor",
    categories: list | None = None,
    confidence: float = 0.5,
    signals: list | None = None,
    streak: int = 1,
) -> UnifiedDriftClassification:
    if signals is None:
        signals = [_make_signal(weight=0.35)]
    if categories is None:
        categories = sorted({s.type for s in signals})
    return UnifiedDriftClassification(
        status="drift_detected",
        severity=severity,
        categories=categories,
        confidence=confidence,
        reasons=list(signals),
        streak=streak,
    )


def _fresh_budgets() -> RepairBudgetState:
    return RepairBudgetState()


def _exhausted_budgets(scope: str) -> RepairBudgetState:
    """Return a budget state with *scope* exhausted via repeated applies."""
    state = RepairBudgetState(
        config=RepairBudgetConfig(
            max_cycle=5, max_subgoal=5, max_plan=5, max_global=5
        )
    )
    for _ in range(5):
        state = apply_repair_budget(state, scope)
    return state


def _dummy_plan_state() -> object:
    """Placeholder plan state — not deeply inspected in 2.10.3."""
    return object()


def _dummy_subgoal_state() -> object:
    """Placeholder subgoal state."""
    return object()


def _dummy_segment_state() -> object:
    """Placeholder segment state."""
    return object()


# ═══════════════════════════════════════════════════════════════════════════════
# ArbitrationDecision dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestArbitrationDecision:
    """Tests for the ArbitrationDecision dataclass itself."""

    def test_valid_construction(self) -> None:
        d = ArbitrationDecision(action="repair", reason="test")
        assert d.action == "repair"
        assert d.reason == "test"
        assert d.metadata == {}

    def test_all_valid_actions(self) -> None:
        for action in ("repair", "replan", "regen_segment", "regen_subgoal",
                       "catastrophic"):
            d = ArbitrationDecision(action=action, reason="ok")
            assert d.action == action

    def test_invalid_action_raises(self) -> None:
        with pytest.raises(ValueError):
            ArbitrationDecision(action="invalid", reason="bad")

    def test_non_string_reason_raises(self) -> None:
        with pytest.raises(ValueError):
            ArbitrationDecision(action="repair", reason=42)  # type: ignore[arg-type]

    def test_metadata_defensive_copy(self) -> None:
        meta = {"key": ["mutable"]}
        d = ArbitrationDecision(action="repair", reason="ok", metadata=meta)
        meta["key"].append("changed")
        assert d.metadata["key"] == ["mutable"]


# ═══════════════════════════════════════════════════════════════════════════════
# Catastrophic drift
# ═══════════════════════════════════════════════════════════════════════════════


class TestCatastrophicDrift:
    """Catastrophic severity → 'catastrophic' action immediately."""

    def test_catastrophic_immediate(self) -> None:
        classification = _make_classification(
            severity="catastrophic",
            signals=[_make_signal(weight=0.80)],
            confidence=0.95,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "catastrophic"

    def test_catastrophic_ignores_budgets(self) -> None:
        """Catastrophic drift bypasses budget exhaustion."""
        classification = _make_classification(
            severity="catastrophic",
            signals=[_make_signal(weight=0.80)],
            confidence=0.95,
        )
        budgets = _exhausted_budgets("global")
        result = decide_arbitration_action(
            classification, budgets,
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "catastrophic"

    def test_catastrophic_ignores_confidence(self) -> None:
        """Low confidence doesn't downgrade catastrophic."""
        classification = _make_classification(
            severity="catastrophic",
            signals=[_make_signal(weight=0.80)],
            confidence=0.15,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "catastrophic"


# ═══════════════════════════════════════════════════════════════════════════════
# Budget exhaustion
# ═══════════════════════════════════════════════════════════════════════════════


class TestBudgetExhaustion:
    """Budget exhaustion must override severity-based decisions."""

    def test_global_exhausted_replan(self) -> None:
        classification = _make_classification(severity="minor")
        budgets = _exhausted_budgets("global")
        result = decide_arbitration_action(
            classification, budgets,
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "replan"

    def test_plan_exhausted_replan(self) -> None:
        classification = _make_classification(severity="minor")
        budgets = _exhausted_budgets("plan")
        result = decide_arbitration_action(
            classification, budgets,
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "replan"

    def test_subgoal_exhausted_regen_subgoal(self) -> None:
        classification = _make_classification(severity="minor")
        budgets = _exhausted_budgets("subgoal")
        result = decide_arbitration_action(
            classification, budgets,
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "regen_subgoal"

    def test_segment_exhausted_regen_segment(self) -> None:
        classification = _make_classification(severity="minor")
        budgets = _exhausted_budgets("cycle")
        result = decide_arbitration_action(
            classification, budgets,
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "regen_segment"

    def test_cycle_exhausted_triggers_regen_segment(self) -> None:
        """Cycle budget exhaustion triggers regen_segment via budget check."""
        classification = _make_classification(severity="minor")
        budgets = _exhausted_budgets("cycle")
        result = decide_arbitration_action(
            classification, budgets,
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "regen_segment"

    def test_global_exhausted_overrides_major(self) -> None:
        """Even major severity is overridden by global budget exhaustion."""
        classification = _make_classification(
            severity="major",
            signals=[_make_signal(weight=0.50)],
        )
        budgets = _exhausted_budgets("global")
        result = decide_arbitration_action(
            classification, budgets,
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "replan"


# ═══════════════════════════════════════════════════════════════════════════════
# Severity rules
# ═══════════════════════════════════════════════════════════════════════════════


class TestSeverityRules:
    """Severity maps to preferred actions."""

    def test_minor_structural_repair(self) -> None:
        classification = _make_classification(
            severity="minor",
            signals=[_make_signal(source="structural", weight=0.30)],
            confidence=0.5,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "repair"

    def test_major_behavioural_regen_segment(self) -> None:
        classification = _make_classification(
            severity="major",
            signals=[_make_signal(source="behavioural", weight=0.55)],
            confidence=0.5,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "regen_segment"

    def test_major_structural_regen_segment(self) -> None:
        """Major + structural → escalated from repair to regen_segment."""
        classification = _make_classification(
            severity="major",
            signals=[_make_signal(source="structural", weight=0.55)],
            confidence=0.5,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "regen_segment"


# ═══════════════════════════════════════════════════════════════════════════════
# Category rules
# ═══════════════════════════════════════════════════════════════════════════════


class TestCategoryRules:
    """Drift category determines preferred action."""

    def test_structural_repair(self) -> None:
        classification = _make_classification(
            severity="minor",
            signals=[_make_signal(source="structural", weight=0.30)],
            confidence=0.5,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "repair"

    def test_behavioural_regen_segment(self) -> None:
        classification = _make_classification(
            severity="minor",
            signals=[_make_signal(source="behavioural", weight=0.30)],
            confidence=0.5,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "regen_segment"

    def test_temporal_regen_segment(self) -> None:
        classification = _make_classification(
            severity="minor",
            signals=[_make_signal(source="temporal", weight=0.30)],
            confidence=0.5,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "regen_segment"

    def test_semantic_repair_minor(self) -> None:
        """Semantic + minor → repair."""
        classification = _make_classification(
            severity="minor",
            signals=[_make_signal(source="semantic", weight=0.30)],
            confidence=0.5,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "repair"

    def test_semantic_major_escalates(self) -> None:
        """Semantic + major → escalated to regen_segment."""
        classification = _make_classification(
            severity="major",
            signals=[_make_signal(source="semantic", weight=0.55)],
            confidence=0.5,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "regen_segment"

    def test_dominant_category_by_weight(self) -> None:
        """When multiple sources exist, highest‑weight signal dominates."""
        signals = [
            _make_signal(source="structural", weight=0.20),
            _make_signal(source="behavioural", weight=0.55, type_="wrong_capability"),
        ]
        classification = _make_classification(
            severity="major",
            signals=signals,
            categories=["shape_mismatch", "wrong_capability"],
            confidence=0.5,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        # behavioural dominates → regen_segment
        assert result.action == "regen_segment"


# ═══════════════════════════════════════════════════════════════════════════════
# Confidence rules
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfidenceRules:
    """Confidence tier adjusts or overrides the base action."""

    def test_low_confidence_forces_repair(self) -> None:
        """Low confidence (< 0.4) forces repair regardless of severity."""
        classification = _make_classification(
            severity="major",
            signals=[_make_signal(source="behavioural", weight=0.55)],
            confidence=0.25,  # low
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "repair"

    def test_medium_confidence_follows_severity(self) -> None:
        """Medium confidence (0.4–0.7) follows severity/category rules."""
        classification = _make_classification(
            severity="major",
            signals=[_make_signal(source="behavioural", weight=0.55)],
            confidence=0.55,  # medium
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "regen_segment"

    def test_high_confidence_escalates(self) -> None:
        """High confidence (≥ 0.7) escalates one level."""
        classification = _make_classification(
            severity="minor",
            signals=[_make_signal(source="structural", weight=0.30)],
            confidence=0.85,  # high
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        # repair → escalated to replan by high confidence
        assert result.action == "replan"

    def test_high_confidence_escalates_major(self) -> None:
        """High confidence escalates major severity too."""
        classification = _make_classification(
            severity="major",
            signals=[_make_signal(source="behavioural", weight=0.55)],
            confidence=0.88,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        # regen_segment → escalated to regen_subgoal
        assert result.action == "regen_subgoal"

    def test_confidence_boundary_low_to_medium(self) -> None:
        """Confidence = 0.4 is medium tier."""
        classification = _make_classification(
            severity="major",
            signals=[_make_signal(source="behavioural", weight=0.55)],
            confidence=0.4,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "regen_segment"

    def test_confidence_boundary_medium_to_high(self) -> None:
        """Confidence = 0.7 is high tier."""
        classification = _make_classification(
            severity="minor",
            signals=[_make_signal(source="structural", weight=0.30)],
            confidence=0.7,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        # repair → escalated to replan
        assert result.action == "replan"


# ═══════════════════════════════════════════════════════════════════════════════
# Determinism
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeterminism:
    """Same inputs must always produce the same output."""

    def test_deterministic_output(self) -> None:
        classification = _make_classification(
            severity="major",
            signals=[_make_signal(source="temporal", weight=0.55)],
            confidence=0.60,
        )
        budgets = _fresh_budgets()

        results = [
            decide_arbitration_action(
                classification, budgets,
                _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
            )
            for _ in range(10)
        ]
        for r in results:
            assert r.action == results[0].action
            assert r.reason == results[0].reason
            assert r.metadata == results[0].metadata

    def test_deterministic_with_exhausted_budgets(self) -> None:
        classification = _make_classification(severity="minor")
        budgets = _exhausted_budgets("global")

        results = [
            decide_arbitration_action(
                classification, budgets,
                _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
            )
            for _ in range(10)
        ]
        for r in results:
            assert r.action == "replan"


# ═══════════════════════════════════════════════════════════════════════════════
# Input immutability
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoMutation:
    """Arbitration must never mutate any input."""

    def test_budgets_not_mutated(self) -> None:
        classification = _make_classification(severity="minor")
        budgets = _fresh_budgets()
        budgets_before = budgets.to_dict()

        decide_arbitration_action(
            classification, budgets,
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert budgets.to_dict() == budgets_before

    def test_classification_not_mutated(self) -> None:
        classification = _make_classification(severity="minor")
        categories_before = list(classification.categories)
        reasons_before = list(classification.reasons)

        decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert classification.categories == categories_before
        assert classification.reasons == reasons_before

    def test_budgets_not_mutated_exhausted(self) -> None:
        classification = _make_classification(severity="minor")
        budgets = _exhausted_budgets("global")
        budgets_before = budgets.to_dict()

        decide_arbitration_action(
            classification, budgets,
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert budgets.to_dict() == budgets_before


# ═══════════════════════════════════════════════════════════════════════════════
# JSON safety
# ═══════════════════════════════════════════════════════════════════════════════


class TestJSONSafety:
    """All outputs must be JSON‑serialisable."""

    def test_decision_json_safe(self) -> None:
        classification = _make_classification(severity="major")
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        serialised = json.dumps({
            "action": result.action,
            "reason": result.reason,
            "metadata": result.metadata,
        })
        assert isinstance(serialised, str)
        parsed = json.loads(serialised)
        assert parsed["action"] == result.action

    def test_metadata_json_safe(self) -> None:
        classification = _make_classification(severity="minor")
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        # Metadata dict must be serialisable
        serialised = json.dumps(result.metadata)
        assert isinstance(serialised, str)


# ═══════════════════════════════════════════════════════════════════════════════
# choose_* helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestChooseHelpers:
    """Individual choose_* functions produce correct decisions."""

    def test_choose_repair(self) -> None:
        drift = _make_classification(severity="minor")
        result = choose_repair(drift, _fresh_budgets())
        assert result.action == "repair"
        assert isinstance(result.reason, str)
        assert len(result.reason) > 0

    def test_choose_replan(self) -> None:
        drift = _make_classification(severity="minor")
        budgets = _exhausted_budgets("global")
        result = choose_replan(drift, budgets)
        assert result.action == "replan"
        assert isinstance(result.reason, str)

    def test_choose_regen_segment(self) -> None:
        drift = _make_classification(severity="major")
        result = choose_regen_segment(drift, _fresh_budgets())
        assert result.action == "regen_segment"
        assert isinstance(result.reason, str)

    def test_choose_regen_subgoal(self) -> None:
        drift = _make_classification(severity="major")
        budgets = _exhausted_budgets("subgoal")
        result = choose_regen_subgoal(drift, budgets)
        assert result.action == "regen_subgoal"
        assert isinstance(result.reason, str)

    def test_choose_catastrophic(self) -> None:
        drift = _make_classification(severity="catastrophic")
        result = choose_catastrophic(drift, _fresh_budgets())
        assert result.action == "catastrophic"
        assert isinstance(result.reason, str)


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge‑case behaviour."""

    def test_zero_confidence(self) -> None:
        """Confidence = 0.0 forces repair (low tier)."""
        classification = _make_classification(
            severity="major",
            signals=[_make_signal(source="behavioural", weight=0.55)],
            confidence=0.0,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        assert result.action == "repair"

    def test_max_confidence(self) -> None:
        """Confidence = 1.0 escalates."""
        classification = _make_classification(
            severity="minor",
            signals=[_make_signal(source="structural", weight=0.30)],
            confidence=1.0,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        # repair → escalated by high confidence
        assert result.action == "replan"

    def test_mixed_categories(self) -> None:
        """Multiple categories — dominant source by weight."""
        signals = [
            _make_signal(source="temporal", weight=0.60, type_="oscillation"),
            _make_signal(source="structural", weight=0.35, type_="shape_mismatch"),
        ]
        classification = _make_classification(
            severity="major",
            signals=signals,
            categories=["oscillation", "shape_mismatch"],
            confidence=0.5,
        )
        result = decide_arbitration_action(
            classification, _fresh_budgets(),
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        # temporal dominates → regen_segment
        assert result.action == "regen_segment"

    def test_multiple_budgets_exhausted(self) -> None:
        """Global takes priority over plan when both exhausted."""
        budgets = RepairBudgetState(
            config=RepairBudgetConfig(
                max_cycle=5, max_subgoal=5, max_plan=5, max_global=5
            )
        )
        for _ in range(5):
            budgets = apply_repair_budget(budgets, "global")
            budgets = apply_repair_budget(budgets, "plan")

        classification = _make_classification(severity="minor")
        result = decide_arbitration_action(
            classification, budgets,
            _dummy_plan_state(), _dummy_subgoal_state(), _dummy_segment_state(),
        )
        # global exhausted first → replan
        assert result.action == "replan"