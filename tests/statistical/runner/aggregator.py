"""
aggregator.py — ConformanceResult and aggregation logic.

Pure functions that aggregate per-run metrics into a single result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from tests.statistical.runner.metrics import extract_all_metrics


@dataclass
class ConformanceResult:
    """Aggregated result of a statistical conformance run.

    Attributes
    ----------
    scenario_name : str
        Name of the scenario that was executed.
    backend : str
        Backend used ("simulation" or "real_llm").
    total_runs : int
        Total number of repetitions executed.
    valid_json : int
        Runs where the LLM output was valid JSON.
    schema_valid : int
        Runs where the PromptResponse passed schema validation.
    total_drift : int
        Total drift signals across all runs.
    total_repairs : int
        Total repair proposals across all runs.
    catastrophic_failures : int
        Runs that produced an S1Error.
    total_invariant_violations : int
        Total invariant violations across all runs.
    trace_stability_scores : list[float]
        Per-run trace stability scores (0.0–1.0).
    per_run_metrics : list[dict]
        Full per-run metric dicts for detailed inspection.
    """

    scenario_name: str = ""
    backend: str = "simulation"
    total_runs: int = 0
    valid_json: int = 0
    schema_valid: int = 0
    total_drift: int = 0
    total_repairs: int = 0
    catastrophic_failures: int = 0
    total_invariant_violations: int = 0
    trace_stability_scores: List[float] = field(default_factory=list)
    per_run_metrics: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def json_validity_rate(self) -> float:
        """Proportion of runs with valid JSON (0.0–1.0)."""
        if self.total_runs == 0:
            return 0.0
        return self.valid_json / self.total_runs

    @property
    def schema_validity_rate(self) -> float:
        """Proportion of runs with schema-valid PromptResponse (0.0–1.0)."""
        if self.total_runs == 0:
            return 0.0
        return self.schema_valid / self.total_runs

    @property
    def mean_trace_stability(self) -> float:
        """Mean trace stability score across all runs."""
        if not self.trace_stability_scores:
            return 0.0
        return sum(self.trace_stability_scores) / len(self.trace_stability_scores)

    @property
    def catastrophic_rate(self) -> float:
        """Proportion of runs that catastrophically failed."""
        if self.total_runs == 0:
            return 0.0
        return self.catastrophic_failures / self.total_runs

    @property
    def mean_drift_per_run(self) -> float:
        """Average drift signals per run."""
        if self.total_runs == 0:
            return 0.0
        return self.total_drift / self.total_runs

    @property
    def summary(self) -> Dict[str, Any]:
        """Return a JSON-safe summary dict for printing/serialisation."""
        return {
            "scenario": self.scenario_name,
            "backend": self.backend,
            "total_runs": self.total_runs,
            "json_validity_rate": round(self.json_validity_rate, 4),
            "schema_validity_rate": round(self.schema_validity_rate, 4),
            "total_drift": self.total_drift,
            "mean_drift_per_run": round(self.mean_drift_per_run, 2),
            "total_repairs": self.total_repairs,
            "catastrophic_failures": self.catastrophic_failures,
            "catastrophic_rate": round(self.catastrophic_rate, 4),
            "total_invariant_violations": self.total_invariant_violations,
            "mean_trace_stability": round(self.mean_trace_stability, 4),
        }


def aggregate(
    run_results: List[Dict[str, Any]],
    scenario_name: str = "",
    backend: str = "simulation",
) -> ConformanceResult:
    """Aggregate per-run results into a ConformanceResult.

    Parameters
    ----------
    run_results : list[dict]
        Raw per-run result dicts.
    scenario_name : str
        Name of the scenario for reporting.
    backend : str
        Backend used.

    Returns
    -------
    ConformanceResult
        Aggregated result with computed rates.
    """
    result = ConformanceResult(
        scenario_name=scenario_name,
        backend=backend,
        total_runs=len(run_results),
    )

    for run in run_results:
        m = extract_all_metrics(run)
        result.per_run_metrics.append(m)

        if m["json_valid"]:
            result.valid_json += 1
        if m["schema_valid"]:
            result.schema_valid += 1
        result.total_drift += m["drift_count"]
        result.total_repairs += m["repair_count"]
        if m["is_catastrophic"]:
            result.catastrophic_failures += 1
        result.total_invariant_violations += m["invariant_violations"]
        result.trace_stability_scores.append(m["trace_stability"])

    return result
