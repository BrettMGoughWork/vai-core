"""Platform-side GatewayPlatformAdapter implementation.

Implements the :class:`~src.gateway.adapters.platform_adapter.GatewayPlatformAdapter`
protocol so the Gateway can submit jobs into the S4 runtime without importing
Platform internals.

The composition root wires a :class:`PlatformGatewayAdapter` instance to the
Gateway at startup.
"""

from __future__ import annotations

from typing import Any

from src.gateway.adapters.platform_adapter import (
    GatewayPlatformAdapter,
    JobRequest,
    JobResult,
    JobStatus,
)


class PlatformGatewayAdapter(GatewayPlatformAdapter):
    """Concrete adapter that Gateway calls to submit jobs to the S4 Platform.

    Uses lazy imports for Platform internals to avoid circular import chains.
    """

    def submit_job(self, request: JobRequest) -> JobStatus:
        """Submit a job request to the S4 runtime.

        Creates a ``ChannelMessage``, wraps it in a ``Job``, registers with the
        ``ControlPlane``, pushes onto the queue, and returns a ``JobStatus``.

        Args:
            request: The :class:`JobRequest` to execute.

        Returns:
            A :class:`JobStatus` with the assigned ``job_id`` and initial state.
        """
        # Lazy imports to break the circular dependency chain
        from src.platform.observability.logging import log_job_created
        from src.platform.runtime import create_job
        from src.platform.runtime.control_plane import (
            control_plane as _default_cp,
        )
        from src.platform.transport.normalization import ChannelMessage

        msg = ChannelMessage(
            input={"text": request.message_text},
            metadata={"channel_type": request.channel_type, **request.metadata},
            channel=request.channel_type,
        )
        job = create_job(msg)
        _default_cp.register_job(job)
        log_job_created(job)

        from src.platform.queue.queue import InMemoryQueue as _default_queue

        _default_queue().push(job)

        return JobStatus(
            job_id=job.job_id,
            state=job.state.value,
        )

    def get_job_status(self, job_id: str) -> JobStatus | None:
        """Retrieve the current status of a previously submitted job.

        Args:
            job_id: The Platform-assigned job identifier.

        Returns:
            A :class:`JobStatus` if the job exists, or ``None`` if not found.
        """
        from src.platform.runtime.job_store import job_store

        job = job_store.get(job_id)
        if job is None:
            return None

        return JobStatus(
            job_id=job.job_id,
            state=job.state.value,
            output=str(job.result) if job.result else None,
        )
