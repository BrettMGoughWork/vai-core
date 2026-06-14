"""
S4.9.4 — Release Checklist for Stratum-4.

Defines the non‑negotiable criteria that must be satisfied before any S4
release is considered shippable.  All checks are run locally, they never
mutate system state, and they produce a structured ``ReleaseReport``.
"""

from src.release.checklist import (
    ReleaseReport,
    CheckResult,
    run_release_checklist,
)

__all__ = [
    "ReleaseReport",
    "CheckResult",
    "run_release_checklist",
]
