"""Supervisor — worker lifecycle + queue health + global correctness for Stratum-4.

The Supervisor Loop monitors worker health via heartbeats, restarts
unhealthy workers deterministically, and escalates to the S4 Control
Plane when thresholds are exceeded.

The Queue Supervisor monitors the job queue for stuck jobs and
backpressure, emitting diagnostic events without mutating state.

The Control Plane Supervisor evaluates global job lifecycle correctness
across S2, S3, and S4, performing deterministic auto-repair when safe.

Worker lifecycle usage::
    loop = SupervisorLoop(config=SupervisorConfig(pool_concurrency=4))
    loop.collect_heartbeats([...])
    decision = loop.evaluate(now=time.time())

Queue supervisor usage::
    qs = QueueSupervisor(config=QueueSupervisorConfig())
    decision = qs.evaluate(metrics, now=time.time())

Control plane supervisor usage::
    cps = ControlPlaneSupervisor(config=ControlPlaneSupervisorConfig())
    decision = cps.evaluate(snapshots, active_workers, now=time.time())
"""

from src.platform.supervisor.supervisor_loop import (
    SupervisorConfig,
    SupervisorDecision,
    SupervisorEscalation,
    SupervisorLoop,
    WorkerHealth,
    WorkerHeartbeat,
    WorkerRestartEvent,
)

from src.platform.supervisor.queue_supervisor import (
    QueueBackpressureEvent,
    QueueMetrics,
    QueueSupervisor,
    QueueSupervisorConfig,
    QueueSupervisorDecision,
    QueueSupervisorEscalation,
    StuckJobEvent,
)

from src.platform.supervisor.control_plane_supervisor import (
    AutoRepairEvent,
    ControlPlaneEscalation,
    ControlPlaneSupervisor,
    ControlPlaneSupervisorConfig,
    ControlPlaneSupervisorDecision,
    InconsistencyEvent,
    JobStateSnapshot,
)

__all__ = [
    # Worker supervisor
    "SupervisorConfig",
    "SupervisorDecision",
    "SupervisorEscalation",
    "SupervisorLoop",
    "WorkerHealth",
    "WorkerHeartbeat",
    "WorkerRestartEvent",
    # Queue supervisor
    "QueueBackpressureEvent",
    "QueueMetrics",
    "QueueSupervisor",
    "QueueSupervisorConfig",
    "QueueSupervisorDecision",
    "QueueSupervisorEscalation",
    "StuckJobEvent",
    # Control plane supervisor
    "AutoRepairEvent",
    "ControlPlaneEscalation",
    "ControlPlaneSupervisor",
    "ControlPlaneSupervisorConfig",
    "ControlPlaneSupervisorDecision",
    "InconsistencyEvent",
    "JobStateSnapshot",
]
