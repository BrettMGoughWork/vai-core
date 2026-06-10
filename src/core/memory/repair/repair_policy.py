"""
Phase 2.17.2 — Repair Policy Engine
====================================

Deterministic action ranking based on historical success/failure rates.

The policy engine ranks repair actions for a given drift type using:
  - Historical success rate (from RepairLearningStore)
  - Consecutive failure count (to avoid repeated failures)
  - Budget awareness (via RepairBudgetState)

Rules (applied in order):
  1. Actions with ≥3 consecutive failures are demoted to the end.
  2. Actions with ≥80% success rate are promoted to the front.
  3. Actions neither promoted nor demoted keep their original position.
  4. Promoted actions are further sorted by descending success rate.
  5. Ties are broken by original order.

All ranking is deterministic — no LLM, no randomness, no I/O.
"""

from __future__ import annotations

from typing import List, Tuple

from .repair_types import RepairAction
from .repair_learning_types import RepairPolicy
from .repair_learning_store import RepairLearningStore


def rank_actions(
    actions: Tuple[RepairAction, ...],
    drift_type: str,
    store: RepairLearningStore,
    policy: RepairPolicy | None = None,
) -> Tuple[RepairAction, ...]:
    """Rank repair actions deterministically based on historical success.

    Parameters
    ----------
    actions : Tuple[RepairAction, ...]
        The actions from build_repair_plan() to rank.
    drift_type : str
        The error_type from BreakageError these actions address.
    store : RepairLearningStore
        The learning store with historical outcome records.
    policy : RepairPolicy or None
        Ranking thresholds. Uses sensible defaults when None.

    Returns
    -------
    Tuple[RepairAction, ...]
        Actions in priority order (best first).
    """
    if not actions:
        return actions

    if policy is None:
        policy = RepairPolicy()

    # Build ranking info: (action, score, original_index)
    ranked: List[Tuple[RepairAction, float, int]] = []
    for i, action in enumerate(actions):
        success_rate = store.success_rate(drift_type, action.action_type)
        consecutive_fails = store.consecutive_failures(drift_type, action.action_type)

        # Compute score — higher is better
        if consecutive_fails >= policy.failure_threshold:
            score = -1.0  # Demoted below all untested actions
        elif success_rate >= policy.success_threshold:
            score = 2.0 + success_rate  # Promoted above all others
        else:
            score = 0.0  # Neutral — preserves original relative order

        ranked.append((action, score, i))

    # Sort: score descending, then original index ascending (stable tiebreak)
    ranked.sort(key=lambda x: (-x[1], x[2]))

    # Apply max_actions_per_cycle cap
    if len(ranked) > policy.max_actions_per_cycle:
        ranked = ranked[:policy.max_actions_per_cycle]

    return tuple(a for a, _, _ in ranked)


def select_best_action(
    actions: Tuple[RepairAction, ...],
    drift_type: str,
    store: RepairLearningStore,
    policy: RepairPolicy | None = None,
) -> RepairAction | None:
    """Select the single best action for a given drift type.

    Returns the first action after ranking, or None if actions is empty.
    """
    ranked = rank_actions(actions, drift_type, store, policy)
    if not ranked:
        return None
    return ranked[0]
