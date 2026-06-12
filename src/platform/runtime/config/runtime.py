"""Runtime-level configuration dataclasses.

Configurations are grouped by subsystem.  Each dataclass maps to a
specific factory or backend, keeping the runtime DI chain explicit.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.platform.runtime.scheduling.policy import SchedulingMode
from src.platform.runtime.worker_pool.isolation import IsolationMode


@dataclass
class RuntimeConcurrencyConfig:
    """Top-level concurrency configuration for the Stratum-4 runtime.

    Attributes:
        isolation: Concurrency backend (threads or processes).
        concurrency: Number of workers to spawn.
        tick_interval: Sleep gap (seconds) between handler invocations
            when no work is available.
    """

    isolation: IsolationMode = IsolationMode.THREADS
    concurrency: int = 1
    tick_interval: float = 0.05


@dataclass
class SchedulingConfig:
    """Configuration for the job scheduling layer.

    Attributes:
        scheduling_mode: The policy to use when selecting the next job.
    """

    scheduling_mode: SchedulingMode = SchedulingMode.FIFO


@dataclass
class HeartbeatConfig:
    """Configuration for the heartbeat subsystem.

    Attributes:
        interval_seconds: How often each worker emits a heartbeat.
        timeout_seconds: Maximum age before a worker is considered unhealthy.
    """

    interval_seconds: float = 1.0
    timeout_seconds: float = 5.0


@dataclass
class ChannelConfig:
    """Configuration for the channel abstraction layer.

    Attributes:
        enabled_channels: Tuple of channel names to activate at startup.
    """

    enabled_channels: tuple[str, ...] = ("cli",)


@dataclass
class CLIChannelConfig:
    """Configuration for the CLI channel adapter.

    Attributes:
        enable_tui: Whether to enable the TUI fallback rendering.
    """

    enable_tui: bool = False


@dataclass
class TUIChannelConfig:
    """Configuration for the TUI channel adapter.

    Attributes:
        enable_heartbeat_panel: Show heartbeat status in the TUI.
        enable_scheduling_panel: Show scheduling decisions in the TUI.
        refresh_interval: Auto-refresh interval in seconds (0 = no auto).
    """

    enable_heartbeat_panel: bool = True
    enable_scheduling_panel: bool = True
    refresh_interval: float = 0.0


@dataclass
class WebChannelConfig:
    """Configuration for the Web (HTTP) channel adapter.

    Attributes:
        enabled: Whether the Web channel is active at startup.
    """

    enabled: bool = True


@dataclass
class WebhookChannelConfig:
    """Configuration for the Webhook channel adapter.

    Attributes:
        enabled_sources: Tuple of webhook source identifiers to accept
            (e.g. ``"github"``, ``"whatsapp"``, ``"generic"``).
    """

    enabled_sources: tuple[str, ...] = ("generic",)


@dataclass
class WebSocketChannelConfig:
    """Configuration for the WebSocket channel adapter.

    Attributes:
        enabled: Whether the WebSocket channel is active at startup.
    """

    enabled: bool = True


@dataclass
class PersistenceConfig:
    """Configuration for the persistence (JobStore) backend.

    Attributes:
        backend:     Persistence implementation — ``"memory"`` or ``"sqlite"``.
        sqlite_path: Path to the SQLite database file (only used when
                     ``backend="sqlite"``).
    """

    backend: str = "memory"
    sqlite_path: str = "vai_jobs.db"
