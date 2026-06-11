"""
Phase 2.10.2 — Repair Budget System
====================================

Deterministic, pure, JSON‑safe budgeting that governs how many repairs may be
attempted per cycle, per subgoal, per plan, and globally.

Prevents runaway repair loops, oscillation, and unbounded correction attempts.

Classes
-------
- ``RepairBudgetConfig`` — static frozen configuration with integer limits
- ``RepairBudgetState`` — frozen dataclass tracking usage across four scopes

Public Functions
----------------
- ``apply_repair_budget(state, scope) -> RepairBudgetState``
    Increments the appropriate scope counter and returns a new state.
- ``is_budget_exhausted(state, scope) -> bool``
    Returns ``True`` when *usage >= limit* for the given scope.

Scopes
------
- ``"cycle"``   — per‑cycle repair attempts
- ``"subgoal"`` — per‑subgoal repair attempts
- ``"plan"``    — per‑plan repair attempts
- ``"global"``  — total repair attempts across the lifetime of a run

Every function:
* is pure and deterministic
* never mutates any input
* raises deterministic errors on invalid scopes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Scope = Literal["cycle", "subgoal", "plan", "global"]

# ── Config ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RepairBudgetConfig:
    """Static configuration for repair budgets.

    All limits must be non‑negative integers.

    Defaults represent sensible starting values and can be overridden per run.
    """

    max_cycle: int = 5
    max_subgoal: int = 10
    max_plan: int = 20
    max_global: int = 50

    def __post_init__(self) -> None:
        for field_name in ("max_cycle", "max_subgoal", "max_plan", "max_global"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"RepairBudgetConfig.{field_name} must be a non‑negative "
                    f"integer, got {value!r}"
                )


# ── State ───────────────────────────────────────────────────────────────────────

_VALID_SCOPES = frozenset({"cycle", "subgoal", "plan", "global"})

_USAGE_FIELDS: dict[str, str] = {
    "cycle": "usage_cycle",
    "subgoal": "usage_subgoal",
    "plan": "usage_plan",
    "global": "usage_global",
}

_LIMIT_FIELDS: dict[str, str] = {
    "cycle": "max_cycle",
    "subgoal": "max_subgoal",
    "plan": "max_plan",
    "global": "max_global",
}


@dataclass(frozen=True)
class RepairBudgetState:
    """Frozen, JSON‑safe tracker for repair budget usage.

    Never mutated — ``apply_repair_budget`` returns a **new** instance.
    """

    usage_cycle: int = 0
    usage_subgoal: int = 0
    usage_plan: int = 0
    usage_global: int = 0
    config: RepairBudgetConfig = field(default_factory=RepairBudgetConfig)

    def __post_init__(self) -> None:
        for field_name in (
            "usage_cycle",
            "usage_subgoal",
            "usage_plan",
            "usage_global",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"RepairBudgetState.{field_name} must be a non‑negative "
                    f"integer, got {value!r}"
                )

    def to_dict(self) -> dict:
        """Return a JSON‑safe dictionary representation."""
        return {
            "usage_cycle": self.usage_cycle,
            "usage_subgoal": self.usage_subgoal,
            "usage_plan": self.usage_plan,
            "usage_global": self.usage_global,
            "config": {
                "max_cycle": self.config.max_cycle,
                "max_subgoal": self.config.max_subgoal,
                "max_plan": self.config.max_plan,
                "max_global": self.config.max_global,
            },
        }


# ── Public API ──────────────────────────────────────────────────────────────────


def _scope_limit(state: RepairBudgetState, scope: Scope) -> int:
    """Return the configured limit for *scope*."""
    limit_name = _LIMIT_FIELDS[scope]
    return getattr(state.config, limit_name)


def _scope_usage(state: RepairBudgetState, scope: Scope) -> int:
    """Return the current usage for *scope*."""
    usage_name = _USAGE_FIELDS[scope]
    return getattr(state, usage_name)


def is_budget_exhausted(state: RepairBudgetState, scope: Scope) -> bool:
    """Return ``True`` when the budget for *scope* has been exhausted.

    Exhaustion is defined as ``usage >= config.limit``.

    Parameters
    ----------
    state : RepairBudgetState
        Current budget state (not mutated).
    scope : Scope
        One of ``"cycle"``, ``"subgoal"``, ``"plan"``, or ``"global"``.

    Returns
    -------
    bool
        ``True`` if the scope has no remaining capacity.
    """
    return _scope_usage(state, scope) >= _scope_limit(state, scope)


def apply_repair_budget(
    state: RepairBudgetState,
    scope: Scope,
) -> RepairBudgetState:
    """Increment the usage counter for *scope* and return a new state.

    Does **not** mutate *state*.  Returns a fresh ``RepairBudgetState``.

    Raises ``ValueError`` if the budget for *scope* is already exhausted.

    Parameters
    ----------
    state : RepairBudgetState
        Current budget state (not mutated).
    scope : Scope
        Which scope to charge the repair attempt against.

    Returns
    -------
    RepairBudgetState
        New state with the scope's usage incremented by one.

    Raises
    ------
    ValueError
        If the budget for *scope* is already exhausted.
    """
    current = _scope_usage(state, scope)
    limit = _scope_limit(state, scope)

    if current >= limit:
        raise ValueError(
            f"Repair budget exhausted for scope '{scope}': "
            f"usage={current}, limit={limit}"
        )

    new_usage = current + 1

    # Build a new state with the incremented counter
    kwargs: dict[str, object] = {
        "usage_cycle": state.usage_cycle,
        "usage_subgoal": state.usage_subgoal,
        "usage_plan": state.usage_plan,
        "usage_global": state.usage_global,
        "config": state.config,
    }
    kwargs[_USAGE_FIELDS[scope]] = new_usage

    return RepairBudgetState(**kwargs)  # type: ignore[arg-type]
