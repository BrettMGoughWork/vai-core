"""
thresholds.py — Thresholds dataclass and evaluation function.

Pure functions — no side effects, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from tests.statistical.runner.aggregator import ConformanceResult


@dataclass(frozen=True)
class Thresholds:
    """Acceptability thresholds for statistical conformance.

    Attributes
    ----------
    min_json_validity : float
        Minimum proportion of runs with valid JSON (0.0–1.0).
    min_schema_validity : float
        Minimum proportion of runs with schema-valid PromptResponse (0.0–1.0).
    max_catastrophic_failures : int
        Maximum allowed catastrophic failures (absolute count).
    max_invariant_violations : int
        Maximum allowed invariant violations (absolute count).
    min_trace_stability : float
        Minimum mean trace stability score (0.0–1.0).
    """

    min_json_validity: float = 0.95
    min_schema_validity: float = 0.90
    max_catastrophic_failures: int = 5
    max_invariant_violations: int = 10
    min_trace_stability: float = 0.80


def evaluate(
    result: ConformanceResult,
    thresholds: Thresholds,
) -> Tuple[bool, list[str]]:
    """Evaluate a ConformanceResult against Thresholds.

    Parameters
    ----------
    result : ConformanceResult
        Aggregated result to evaluate.
    thresholds : Thresholds
        Acceptability thresholds.

    Returns
    -------
    passed : bool
        True if ALL thresholds are met.
    failures : list[str]
        Human-readable list of failed thresholds (empty if passed).
    """
    failures: list[str] = []

    if result.json_validity_rate < thresholds.min_json_validity:
        failures.append(
            f"JSON validity {result.json_validity_rate:.2%} < {thresholds.min_json_validity:.0%}"
        )
    if result.schema_validity_rate < thresholds.min_schema_validity:
        failures.append(
            f"Schema validity {result.schema_validity_rate:.2%} < {thresholds.min_schema_validity:.0%}"
        )
    if result.catastrophic_failures > thresholds.max_catastrophic_failures:
        failures.append(
            f"Catastrophic failures {result.catastrophic_failures} > {thresholds.max_catastrophic_failures}"
        )
    if result.total_invariant_violations > thresholds.max_invariant_violations:
        failures.append(
            f"Invariant violations {result.total_invariant_violations} > {thresholds.max_invariant_violations}"
        )
    if result.mean_trace_stability < thresholds.min_trace_stability:
        failures.append(
            f"Trace stability {result.mean_trace_stability:.2%} < {thresholds.min_trace_stability:.0%}"
        )

    return len(failures) == 0, failures
