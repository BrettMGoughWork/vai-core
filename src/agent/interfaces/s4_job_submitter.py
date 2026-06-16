"""
S5 → S4: Durable Job Submission Protocol
=========================================

Defines the contract between the orchestrator (S5) and the platform
stratum (S4) for durable job submission.

S4 is **optional** — only used when the workflow step requires
durability, restartability, or fan-in/fan-out.  Direct calls to S1
or S3 bypass S4 entirely.

This is the **only** way S5 interacts with S4 — no direct imports of
S4 implementation details.

Contract
--------
- ``submit()`` — submits a durable job and returns a job ID string
- ``submit()`` is synchronous (enqueue, not execute)
- Durability is opt-in via the ``durable`` parameter
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class S4JobSubmitter(Protocol):
    """S5 → S4: Submit a durable job (optional path).

    Implementations enqueue the payload into S4's job system for
    durable execution with supervision, restartability, and
    fan-in/fan-out.
    """

    def submit(
        self,
        payload: Dict[str, Any],
        durable: bool = True,
    ) -> str:
        """Submit a job for durable execution.

        Args:
            payload: The job payload (operation type, arguments,
                     metadata, etc.).
            durable: If True, the job is persisted and supervised.
                     If False, a lightweight non-durable submission
                     is used.

        Returns:
            A job ID string that can be used to track the job's
            progress and retrieve results.
        """
        ...
