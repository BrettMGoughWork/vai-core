"""
Phase 2.17.3 — Counterfactual Repair (Deterministic Only)
==========================================================

Generates and records counterfactual alternatives when a repair action fails.

Counterfactuals are recorded as CounterfactualEntry in the RepairLearningStore.
They track what alternative approach could have been tried instead, enabling
frequency-based scoring for future repair decisions.

Categories:
  - alternative skills      — different capability/tool to apply
  - alternative shapes      — different segment decomposition structure
  - alternative decompositions — different way to break down a subgoal

All counterfactual generation is deterministic — based on the failed
action type, not on LLM reasoning or content inspection.
"""

from __future__ import annotations

from typing import List, Tuple

from .repair_learning_types import CounterfactualEntry
from .repair_learning_store import RepairLearningStore

# ---------------------------------------------------------------------------
# Deterministic counterfactual mapping
# ---------------------------------------------------------------------------

_ACTION_COUNTERFACTUALS: dict[str, List[Tuple[str, str]]] = {
    "REGENERATE_SEGMENT": [
        ("RECONSTRUCT_CHAIN", "Sever the broken link instead of regenerating the segment"),
        ("QUARANTINE_SEGMENT", "Quarantine the mismatched segment instead of regenerating"),
    ],
    "RECONSTRUCT_CHAIN": [
        ("REGENERATE_SEGMENT", "Regenerate a placeholder segment instead of severing the link"),
        ("QUARANTINE_SEGMENT", "Remove the broken segment from the plan entirely"),
    ],
    "REHYDRATE_TIMESTAMP": [
        ("REGENERATE_SEGMENT", "If timestamp corruption is structural, regenerate the segment"),
    ],
    "QUARANTINE_SEGMENT": [
        ("REGENERATE_SEGMENT", "Regenerate a replacement segment instead of removing it"),
        ("RECONSTRUCT_CHAIN", "Sever only the broken parent link instead of full quarantine"),
    ],
}


def generate_counterfactuals(
    drift_type: str,
    failed_action: str,
) -> List[CounterfactualEntry]:
    """Generate counterfactual alternatives for a failed repair action.

    Parameters
    ----------
    drift_type : str
        The error_type from BreakageError that triggered the repair.
    failed_action : str
        The action_type from RepairAction that failed.

    Returns
    -------
    List[CounterfactualEntry]
        One entry per deterministic alternative. Empty if no alternatives
        are defined for this action type.
    """
    alternatives = _ACTION_COUNTERFACTUALS.get(failed_action, [])
    return [
        CounterfactualEntry(
            drift_type=drift_type,
            failed_action=failed_action,
            alternative_action=alt_action,
            alternative_details=alt_details,
            frequency=1,
        )
        for alt_action, alt_details in alternatives
    ]


def record_failure_with_counterfactuals(
    drift_type: str,
    failed_action: str,
    store: RepairLearningStore,
) -> Tuple[CounterfactualEntry, ...]:
    """Generate counterfactuals and record them in the store.

    Convenience function that generates counterfactuals for the failed
    action and records each one in the store (with frequency deduplication).

    Parameters
    ----------
    drift_type : str
        The error_type from BreakageError.
    failed_action : str
        The action_type from RepairAction that failed.
    store : RepairLearningStore
        The learning store to record counterfactuals into.

    Returns
    -------
    Tuple[CounterfactualEntry, ...]
        The counterfactual entries that were recorded.
    """
    entries = generate_counterfactuals(drift_type, failed_action)
    for entry in entries:
        store.record_counterfactual(entry)
    return tuple(entries)


def get_alternative_actions(
    drift_type: str,
    store: RepairLearningStore,
) -> Tuple[str, ...]:
    """Get alternative actions that have been counterfactually suggested
    for a given drift type, sorted by frequency (most frequent first).

    Parameters
    ----------
    drift_type : str
        The error_type from BreakageError.
    store : RepairLearningStore
        The learning store with counterfactual entries.

    Returns
    -------
    Tuple[str, ...]
        Alternative action_type strings, most frequent first.
    """
    cf_entries = store.get_counterfactuals()
    relevant = [cf for cf in cf_entries if cf.drift_type == drift_type]
    # Sort by frequency descending
    relevant.sort(key=lambda cf: -cf.frequency)
    # Deduplicate while preserving order
    seen: set[str] = set()
    result: List[str] = []
    for cf in relevant:
        if cf.alternative_action not in seen:
            seen.add(cf.alternative_action)
            result.append(cf.alternative_action)
    return tuple(result)
