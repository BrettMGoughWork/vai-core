"""
Tests for Phase 2.10.2 — Repair Budget System.

Covers:
- per‑cycle budget enforcement
- per‑subgoal budget enforcement
- per‑plan budget enforcement
- global budget enforcement
- exhaustion detection
- no mutation of inputs
- deterministic output
- JSON‑safe
"""

from __future__ import annotations

import json

import pytest

from src.core.planning.drift.repair_budget import (
    RepairBudgetConfig,
    RepairBudgetState,
    apply_repair_budget,
    is_budget_exhausted,
)


# ═══════════════════════════════════════════════════════════════════════════════
# RepairBudgetConfig
# ═══════════════════════════════════════════════════════════════════════════════


class TestRepairBudgetConfig:
    """Tests for the static configuration."""

    def test_default_values(self) -> None:
        cfg = RepairBudgetConfig()
        assert cfg.max_cycle == 5
        assert cfg.max_subgoal == 10
        assert cfg.max_plan == 20
        assert cfg.max_global == 50

    def test_custom_values(self) -> None:
        cfg = RepairBudgetConfig(
            max_cycle=1,
            max_subgoal=2,
            max_plan=3,
            max_global=4,
        )
        assert cfg.max_cycle == 1
        assert cfg.max_subgoal == 2
        assert cfg.max_plan == 3
        assert cfg.max_global == 4

    def test_zero_limits_allowed(self) -> None:
        cfg = RepairBudgetConfig(
            max_cycle=0,
            max_subgoal=0,
            max_plan=0,
            max_global=0,
        )
        assert cfg.max_cycle == 0

    def test_rejects_negative_max_cycle(self) -> None:
        with pytest.raises(ValueError):
            RepairBudgetConfig(max_cycle=-1)

    def test_rejects_negative_max_subgoal(self) -> None:
        with pytest.raises(ValueError):
            RepairBudgetConfig(max_subgoal=-1)

    def test_rejects_negative_max_plan(self) -> None:
        with pytest.raises(ValueError):
            RepairBudgetConfig(max_plan=-1)

    def test_rejects_negative_max_global(self) -> None:
        with pytest.raises(ValueError):
            RepairBudgetConfig(max_global=-1)

    def test_frozen(self) -> None:
        cfg = RepairBudgetConfig()
        with pytest.raises(Exception):
            cfg.max_cycle = 99  # type: ignore[misc]

    def test_json_safe(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=3, max_subgoal=7, max_plan=15, max_global=30)
        result = json.dumps(
            {
                "max_cycle": cfg.max_cycle,
                "max_subgoal": cfg.max_subgoal,
                "max_plan": cfg.max_plan,
                "max_global": cfg.max_global,
            }
        )
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["max_cycle"] == 3
        assert parsed["max_subgoal"] == 7
        assert parsed["max_plan"] == 15
        assert parsed["max_global"] == 30


# ═══════════════════════════════════════════════════════════════════════════════
# RepairBudgetState
# ═══════════════════════════════════════════════════════════════════════════════


class TestRepairBudgetState:
    """Tests for the budget state."""

    def test_default_state_zero_usage(self) -> None:
        state = RepairBudgetState()
        assert state.usage_cycle == 0
        assert state.usage_subgoal == 0
        assert state.usage_plan == 0
        assert state.usage_global == 0

    def test_custom_state(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=3, max_subgoal=5, max_plan=10, max_global=20)
        state = RepairBudgetState(
            usage_cycle=1,
            usage_subgoal=2,
            usage_plan=3,
            usage_global=4,
            config=cfg,
        )
        assert state.usage_cycle == 1
        assert state.usage_subgoal == 2
        assert state.usage_plan == 3
        assert state.usage_global == 4
        assert state.config.max_cycle == 3

    def test_rejects_negative_usage_cycle(self) -> None:
        with pytest.raises(ValueError):
            RepairBudgetState(usage_cycle=-1)

    def test_rejects_negative_usage_subgoal(self) -> None:
        with pytest.raises(ValueError):
            RepairBudgetState(usage_subgoal=-1)

    def test_rejects_negative_usage_plan(self) -> None:
        with pytest.raises(ValueError):
            RepairBudgetState(usage_plan=-1)

    def test_rejects_negative_usage_global(self) -> None:
        with pytest.raises(ValueError):
            RepairBudgetState(usage_global=-1)

    def test_frozen(self) -> None:
        state = RepairBudgetState()
        with pytest.raises(Exception):
            state.usage_cycle = 99  # type: ignore[misc]

    def test_to_dict(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=3, max_plan=5)
        state = RepairBudgetState(
            usage_cycle=2,
            usage_plan=1,
            config=cfg,
        )
        d = state.to_dict()
        assert d["usage_cycle"] == 2
        assert d["usage_subgoal"] == 0
        assert d["usage_plan"] == 1
        assert d["usage_global"] == 0
        assert d["config"]["max_cycle"] == 3
        assert d["config"]["max_plan"] == 5

    def test_json_safe(self) -> None:
        state = RepairBudgetState(usage_global=7)
        result = json.dumps(state.to_dict())
        parsed = json.loads(result)
        assert parsed["usage_global"] == 7


# ═══════════════════════════════════════════════════════════════════════════════
# is_budget_exhausted
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsBudgetExhausted:
    """Tests for the exhaustion predicate."""

    def test_not_exhausted_when_under_limit(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=5)
        state = RepairBudgetState(usage_cycle=3, config=cfg)
        assert is_budget_exhausted(state, "cycle") is False

    def test_exhausted_when_equal_to_limit(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=5)
        state = RepairBudgetState(usage_cycle=5, config=cfg)
        assert is_budget_exhausted(state, "cycle") is True

    def test_exhausted_when_over_limit(self) -> None:
        cfg = RepairBudgetConfig(max_subgoal=3)
        state = RepairBudgetState(usage_subgoal=4, config=cfg)
        assert is_budget_exhausted(state, "subgoal") is True

    def test_zero_limit_immediately_exhausted(self) -> None:
        cfg = RepairBudgetConfig(max_plan=0)
        state = RepairBudgetState(usage_plan=0, config=cfg)
        assert is_budget_exhausted(state, "plan") is True

    def test_global_budget_exhausted(self) -> None:
        cfg = RepairBudgetConfig(max_global=50)
        state = RepairBudgetState(usage_global=50, config=cfg)
        assert is_budget_exhausted(state, "global") is True

    def test_global_budget_not_exhausted(self) -> None:
        cfg = RepairBudgetConfig(max_global=50)
        state = RepairBudgetState(usage_global=49, config=cfg)
        assert is_budget_exhausted(state, "global") is False

    def test_deterministic(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=3)
        state = RepairBudgetState(usage_cycle=3, config=cfg)
        assert is_budget_exhausted(state, "cycle") is is_budget_exhausted(state, "cycle")


# ═══════════════════════════════════════════════════════════════════════════════
# apply_repair_budget
# ═══════════════════════════════════════════════════════════════════════════════


class TestApplyRepairBudget:
    """Tests for applying (incrementing) the budget."""

    # ── cycle scope ──────────────────────────────────────────────────────────

    def test_cycle_incremented(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=5)
        state = RepairBudgetState(usage_cycle=2, config=cfg)
        new_state = apply_repair_budget(state, "cycle")
        assert new_state.usage_cycle == 3
        # other counters unchanged
        assert new_state.usage_subgoal == 0
        assert new_state.usage_plan == 0
        assert new_state.usage_global == 0

    def test_cycle_exhausted_raises(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=2)
        state = RepairBudgetState(usage_cycle=2, config=cfg)
        with pytest.raises(ValueError, match="exhausted"):
            apply_repair_budget(state, "cycle")

    # ── subgoal scope ────────────────────────────────────────────────────────

    def test_subgoal_incremented(self) -> None:
        cfg = RepairBudgetConfig(max_subgoal=5)
        state = RepairBudgetState(usage_subgoal=3, config=cfg)
        new_state = apply_repair_budget(state, "subgoal")
        assert new_state.usage_subgoal == 4

    def test_subgoal_exhausted_raises(self) -> None:
        cfg = RepairBudgetConfig(max_subgoal=1)
        state = RepairBudgetState(usage_subgoal=1, config=cfg)
        with pytest.raises(ValueError, match="exhausted"):
            apply_repair_budget(state, "subgoal")

    # ── plan scope ───────────────────────────────────────────────────────────

    def test_plan_incremented(self) -> None:
        cfg = RepairBudgetConfig(max_plan=10)
        state = RepairBudgetState(usage_plan=9, config=cfg)
        new_state = apply_repair_budget(state, "plan")
        assert new_state.usage_plan == 10

    def test_plan_exhausted_raises(self) -> None:
        cfg = RepairBudgetConfig(max_plan=3)
        state = RepairBudgetState(usage_plan=3, config=cfg)
        with pytest.raises(ValueError, match="exhausted"):
            apply_repair_budget(state, "plan")

    # ── global scope ─────────────────────────────────────────────────────────

    def test_global_incremented(self) -> None:
        cfg = RepairBudgetConfig(max_global=100)
        state = RepairBudgetState(usage_global=99, config=cfg)
        new_state = apply_repair_budget(state, "global")
        assert new_state.usage_global == 100

    def test_global_exhausted_raises(self) -> None:
        cfg = RepairBudgetConfig(max_global=1)
        state = RepairBudgetState(usage_global=1, config=cfg)
        with pytest.raises(ValueError, match="exhausted"):
            apply_repair_budget(state, "global")

    # ── cross‑scope independence ─────────────────────────────────────────────

    def test_incrementing_one_scope_does_not_affect_others(self) -> None:
        cfg = RepairBudgetConfig(
            max_cycle=10,
            max_subgoal=10,
            max_plan=10,
            max_global=10,
        )
        state = RepairBudgetState(
            usage_cycle=3,
            usage_subgoal=3,
            usage_plan=3,
            usage_global=3,
            config=cfg,
        )
        new_state = apply_repair_budget(state, "cycle")
        # Only cycle incremented
        assert new_state.usage_cycle == 4
        assert new_state.usage_subgoal == 3
        assert new_state.usage_plan == 3
        assert new_state.usage_global == 3

    # ── multiple applications ────────────────────────────────────────────────

    def test_multiple_applications_across_scopes(self) -> None:
        cfg = RepairBudgetConfig(
            max_cycle=5,
            max_subgoal=5,
            max_plan=5,
            max_global=10,
        )
        state = RepairBudgetState(config=cfg)
        state = apply_repair_budget(state, "cycle")
        state = apply_repair_budget(state, "cycle")
        state = apply_repair_budget(state, "subgoal")
        state = apply_repair_budget(state, "global")
        assert state.usage_cycle == 2
        assert state.usage_subgoal == 1
        assert state.usage_plan == 0
        assert state.usage_global == 1

    def test_increment_to_exhaustion(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=3)
        state = RepairBudgetState(usage_cycle=0, config=cfg)
        state = apply_repair_budget(state, "cycle")  # 1
        state = apply_repair_budget(state, "cycle")  # 2
        state = apply_repair_budget(state, "cycle")  # 3 → exhausted
        assert is_budget_exhausted(state, "cycle") is True
        with pytest.raises(ValueError):
            apply_repair_budget(state, "cycle")

    # ── mutation safety ──────────────────────────────────────────────────────

    def test_does_not_mutate_input(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=5)
        state = RepairBudgetState(usage_cycle=2, config=cfg)
        apply_repair_budget(state, "cycle")
        assert state.usage_cycle == 2  # unchanged

    def test_does_not_mutate_config(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=5)
        state = RepairBudgetState(config=cfg)
        apply_repair_budget(state, "cycle")
        assert cfg.max_cycle == 5  # unchanged

    # ── determinism ──────────────────────────────────────────────────────────

    def test_deterministic_output(self) -> None:
        cfg = RepairBudgetConfig(max_global=10)
        state = RepairBudgetState(usage_global=3, config=cfg)
        r1 = apply_repair_budget(state, "global")
        r2 = apply_repair_budget(state, "global")
        assert r1.usage_global == r2.usage_global
        assert r1.config == r2.config

    # ── JSON safety ──────────────────────────────────────────────────────────

    def test_result_to_dict_is_json_safe(self) -> None:
        cfg = RepairBudgetConfig(max_cycle=2)
        state = RepairBudgetState(usage_cycle=1, config=cfg)
        new_state = apply_repair_budget(state, "cycle")
        result = json.dumps(new_state.to_dict())
        parsed = json.loads(result)
        assert parsed["usage_cycle"] == 2
