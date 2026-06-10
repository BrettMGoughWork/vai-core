"""
Phase 2.17.4 — Pattern Recognition
===================================

Deterministic, frequency-based pattern detection for repair outcomes.

Detects patterns from the RepairLearningStore:
  - Promotes patterns with ≥80% success rate
  - Demotes patterns with ≥3 consecutive failures

All thresholds are purely frequency-based — no LLM reasoning,
no semantic analysis, no I/O.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .repair_learning_types import RepairPolicy, PatternMatch, RepairMemoryRecord
from .repair_learning_store import RepairLearningStore


def detect_patterns(
    store: RepairLearningStore,
    policy: RepairPolicy | None = None,
) -> Tuple[PatternMatch, ...]:
    """Detect patterns from all recorded repair outcomes.

    Groups records by (drift_type, action_type), computes success rates
    and consecutive failures, then returns PatternMatch entries for each
    unique combination.

    Parameters
    ----------
    store : RepairLearningStore
        The learning store with historical outcome records.
    policy : RepairPolicy or None
        Thresholds for promotion/demotion. Uses sensible defaults when None.

    Returns
    -------
    Tuple[PatternMatch, ...]
        Patterns sorted: promoted first, then by success_rate descending,
        then by sample_count descending.
    """
    if policy is None:
        policy = RepairPolicy()

    records = store.get_records()
    if not records:
        return ()

    # Group by (drift_type, action_type)
    groups: Dict[Tuple[str, str], List[RepairMemoryRecord]] = {}
    for r in records:
        key = (r.drift_type, r.action_type)
        groups.setdefault(key, []).append(r)

    patterns: List[PatternMatch] = []
    for (drift_type, action_type), group in groups.items():
        successes = sum(1 for r in group if r.outcome == "success")
        success_rate = successes / len(group)
        consecutive_fails = store.consecutive_failures(drift_type, action_type)

        promoted = success_rate >= policy.success_threshold
        demoted = consecutive_fails >= policy.failure_threshold

        patterns.append(
            PatternMatch(
                drift_type=drift_type,
                best_action=action_type,
                success_rate=success_rate,
                sample_count=len(group),
                promoted=promoted,
                demoted=demoted,
            )
        )

    # Sort: promoted → success_rate desc → sample_count desc
    patterns.sort(key=lambda p: (-int(p.promoted), -p.success_rate, -p.sample_count))

    return tuple(patterns)


def get_best_action_for_drift(
    drift_type: str,
    store: RepairLearningStore,
    policy: RepairPolicy | None = None,
) -> str | None:
    """Find the best action for a given drift type.

    Prioritises promoted patterns (≥80% success) that haven't been demoted
    (≥3 consecutive failures). Falls back to the highest success-rate action
    for the drift type, even if not promoted.

    Returns None when no pattern exists for this drift type.
    """
    patterns = detect_patterns(store, policy)

    # Priority 1: Promoted, not demoted
    for p in patterns:
        if p.drift_type == drift_type and p.promoted and not p.demoted:
            return p.best_action

    # Priority 2: Highest success rate (even if not promoted)
    for p in patterns:
        if p.drift_type == drift_type:
            return p.best_action

    return None
