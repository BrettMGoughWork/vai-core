"""S5.4 — Agent → Platform Route Dispatch.

Phase 5.2 rewrite: accepts ``Route`` (from the Agent Router) instead of the
old ``CognitiveLoopResult`` / ``ActionIntent`` pipeline.

The dispatch layer is now a thin switch on ``Route.destination``:

* ``s4b`` — submit a platform job
* ``runtime`` / ``s6`` — terminal (no platform action needed)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from src.agent.router import Route


# ── Types ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class JobDispatchResult:
    """Result of dispatching a ``Route`` to the Platform layer.

    Attributes:
        dispatched_jobs: Mapping of ``job_id`` → ``destination`` for every
                         successfully submitted job.
        errors:          (destination, message) pairs for failed dispatches.
    """

    dispatched_jobs: dict[str, str] = field(default_factory=dict)
    errors: list[tuple[str, str]] = field(default_factory=list)


# ── Dispatch ──────────────────────────────────────────────────────────────


def dispatch_route(
    route: Route,
    *,
    submit_job_callable: Callable[..., str] | None = None,
) -> JobDispatchResult:
    """Dispatch a ``Route`` to the appropriate destination handler.

    Only ``DEST_S4B`` routes currently submit platform jobs; all others
    (``runtime``, ``s6``) are terminal from the dispatch perspective.

    Args:
        route:
            The routing decision from the Agent Router.
        submit_job_callable:
            A callable that accepts a ``dict`` payload and returns a
            ``job_id`` string.  Only required for ``s4b`` routes.

    Returns:
        A ``JobDispatchResult`` summarising what was dispatched.
    """
    from src.agent.router import DEST_S4B

    dispatched: dict[str, str] = {}
    errors: list[tuple[str, str]] = []

    if route.destination == DEST_S4B:
        if submit_job_callable is None:
            errors.append(("s4b", "No submit_job_callable provided"))
            return JobDispatchResult(errors=errors)

        try:
            job_id = submit_job_callable(route.payload)
            dispatched[job_id] = route.destination
        except Exception as exc:
            errors.append((route.destination, str(exc)))

    return JobDispatchResult(dispatched_jobs=dispatched, errors=errors)
