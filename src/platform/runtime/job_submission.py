"""Job submission — Platform stratum.

Thin wrapper around ``create_job()`` + ``Queue.push()`` so that consuming
strata never call ``Queue.push()`` directly.  This is the **only** public
path for submitting jobs to the Platform layer from other strata.

Usage
-----
.. code-block:: python

    from src.platform.interfaces import submit_job

    job_id = submit_job(channel_message, queue)

The caller owns the ``Queue`` instance (dependency injection).  The
function itself is pure — it creates a ``Job`` and pushes it, then
returns the ``job_id``.
"""

from __future__ import annotations

from src.platform.queue.queue import Queue
from src.platform.runtime.job import create_job
from src.platform.transport.normalization import ChannelMessage


def submit_job(channel_message: ChannelMessage, queue: Queue) -> str:
    """Create a ``Job`` from *channel_message* and enqueue it.

    This is the Platform-stratum boundary for job submission.  Consuming
    strata should pass a ``Queue`` instance obtained through dependency
    injection — they never call ``Queue.push()`` directly.

    Args:
        channel_message: The normalized message to wrap in a ``Job``.
        queue:          A FIFO queue instance (from ``src.platform.queue``).

    Returns:
        The ``job_id`` of the newly created and enqueued job.

    Raises:
        Any exception originating from ``queue.push()`` is propagated
        to the caller.  No retry or error wrapping is performed here —
        that is the responsibility of the caller or an orchestrator.
    """
    job = create_job(channel_message)
    return queue.push(job)
