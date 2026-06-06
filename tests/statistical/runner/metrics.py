"""
metrics.py — Pure metric extractors for individual conformance runs.

Each function accepts a run result dict and returns a typed metric.
All functions are deterministic, side-effect-free, and JSON-safe.
"""

from __future__ import annotations

from typing import Any, Dict


# ──────────────────────────────────────────────────────────────────────────────
# Per-run metric extractors
# ──────────────────────────────────────────────────────────────────────────────


def json_validity(run: Dict[str, Any]) -> bool:
    """Whether the raw LLM output was valid JSON (or the response was a PromptResponse)."""
    return run.get("json_valid", False)


def schema_validity(run: Dict[str, Any]) -> bool:
    """Whether the PromptResponse passed schema validation."""
    return run.get("schema_valid", False)


def drift_count(run: Dict[str, Any]) -> int:
    """Number of drift signals in the response."""
    s2_updates = run.get("s2_updates", {})
    signals = s2_updates.get("drift_signals", [])
    return len(signals)


def repair_count(run: Dict[str, Any]) -> int:
    """Number of repair proposals in the response."""
    s2_updates = run.get("s2_updates", {})
    proposals = s2_updates.get("repair_proposals", [])
    return len(proposals)


def is_catastrophic(run: Dict[str, Any]) -> bool:
    """Whether the run resulted in an S1Error (catastrophic failure)."""
    return run.get("is_error", False)


def invariant_violations(run: Dict[str, Any]) -> int:
    """Count of invariant violations (raw strings, missing keys, non-JSON-safe)."""
    violations = 0
    if run.get("has_raw_strings", False):
        violations += 1
    if not run.get("is_json_safe", True):
        violations += 1
    if run.get("missing_trace_keys", False):
        violations += 1
    return violations


def trace_stability_score(run: Dict[str, Any]) -> float:
    """A 0.0–1.0 score measuring trace structure validity.

    1.0 = trace has all required keys and no raw strings.
    0.0 = trace is invalid or missing.
    """
    if run.get("missing_trace_keys", True):
        return 0.0
    if run.get("has_raw_strings", True):
        return 0.5
    return 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Batch extraction
# ──────────────────────────────────────────────────────────────────────────────


def extract_all_metrics(run: Dict[str, Any]) -> Dict[str, Any]:
    """Extract all metrics from a single run result dict.

    Returns a flat dict suitable for aggregation.
    """
    return {
        "json_valid": json_validity(run),
        "schema_valid": schema_validity(run),
        "drift_count": drift_count(run),
        "repair_count": repair_count(run),
        "is_catastrophic": is_catastrophic(run),
        "invariant_violations": invariant_violations(run),
        "trace_stability": trace_stability_score(run),
    }
