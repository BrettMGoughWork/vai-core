"""GatewayPlatformAdapter — the single boundary interface between Gateway and Platform.

Gateway imports this protocol. Platform implements it. The composition root wires
them together. Gateway never imports Platform internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class JobRequest:
    """A job request from the Gateway to the Platform.

    Attributes:
        channel_type: Channel identifier (``"cli"``, ``"web"``, ``"slack"``, …).
        message_text: The user's message text.
        user_id:      Optional sender identity.
        metadata:     Additional channel-level metadata.
    """

    channel_type: str
    message_text: str
    user_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class JobStatus:
    """Status summary for a submitted job.

    Attributes:
        job_id: The Platform-assigned job identifier.
        state:  Current state (``"pending"``, ``"running"``, ``"completed"``,
                ``"failed"``).
        output: Human-readable output text (if completed).
        error:  Error message (if failed).
    """

    job_id: str
    state: str
    output: str | None = None
    error: str | None = None


# Convenience alias for type annotations
JobResult = JobStatus


class GatewayPlatformAdapter(Protocol):
    """Protocol that Platform implements for Gateway communication.

    Gateway calls these methods instead of importing Platform internals.
    Platform provides the concrete implementation during startup.
    """

    def submit_job(self, request: JobRequest) -> JobStatus:
        """Submit a job request to the Platform.

        Args:
            request: The :class:`JobRequest` to execute.

        Returns:
            A :class:`JobStatus` with the assigned ``job_id`` and initial state.
        """
        ...

    def get_job_status(self, job_id: str) -> JobStatus | None:
        """Retrieve the current status of a previously submitted job.

        Args:
            job_id: The Platform-assigned job identifier.

        Returns:
            A :class:`JobStatus` if the job exists, or ``None`` if not found.
        """
        ...
