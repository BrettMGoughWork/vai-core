# Event Substrate — S4 Queue System

**Purpose:** Universal event bus for all Stratum-4 internal communication. All
inbound channel messages, supervision events, and internal job routing flow
through the queue.

---

## Architecture

```
 Channel → Normalizer → Queue → Worker Pool → ControlPlane → Store
                                ↕
                         Queue Supervisor (diagnostic)
```

The queue is a FIFO buffer with **lease semantics**: a pop removes the item
from the main queue but tracks it as in-flight until acknowledged or nacked.

---

## Queue Abstract Base

File: `src/platform/queue/queue.py`

The `Queue` protocol defines the contract:

```python
class Queue(Protocol):
    def push(self, job: "Job") -> None: ...
    def pop(self) -> tuple[str, "Job"] | None: ...  # (token, job)
    def ack(self, token: str) -> None: ...
    def requeue(self, token: str, delay: float = 0.0) -> None: ...
    def nack(self, token: str, poison: bool = False) -> None: ...
```

The `LeaseManager` (`src/platform/queue/lease_manager.py`) adds timeout and
retry tracking atop any queue implementation. It monitors in-flight items and
releases leases that exceed the configured timeout window.

## Implementations

### InMemoryQueue

`deque`-based FIFO for the pending queue with a `dict` of leased (in-flight)
items indexed by a unique lease token. Default for local dev and tests.

```python
queue = InMemoryQueue()
queue.push(job)                       # append to deque
token = queue.pop()                   # move deque → in_flight dict
queue.ack(token)                      # remove from in_flight
queue.requeue(token)                  # in_flight → deque (retry)
queue.nack(token, poison=True)        # in_flight → dead letter
```

### RedisListQueue

File: `src/platform/queue/backends/redis_queue.py`

- Uses `RPOPLPUSH` for atomic pop-and-lease: pops from the main list and
  atomically pushes to an in-flight list.
- `ack` removes from in-flight list; `requeue` pushes back to the main list.
- `nack` moves to a dead-letter list.
- JSON serialisation of `Job` objects.

### Factory

`src/platform/queue/factory.py` selects and configures the queue at startup:

```python
def create_queue(config: S4Config) -> Queue:
    backend = config["queue"]["backend"]
    if backend == "in_memory":
        return InMemoryQueue()
    elif backend == "redis":
        return RedisListQueue(config["queue"]["redis_url"])
    ...
```

---

## Push/Pop Lifecycle

```
 push          pop              ack
  │             │                │
  ▼             ▼                ▼
┌──────┐    ┌────────┐    ┌───────────┐
│Queue │───→│In-Flight│───→│Completed  │
│(FIFO)│    │(leased) │    │(removed)  │
└──────┘    └────────┘    └───────────┘
                │
                ├── requeue → Queue (retry)
                │
                └── nack → Dead Letter (poison)
```

---

## Backpressure Semantics

| Condition | Behaviour |
|-----------|-----------|
| Queue depth exceeds threshold | Queue supervisor emits `queue_backpressure` event |
| Push rate > pop rate | Workers are saturated; supervisor detects via heartbeat |
| In-flight count high | Jobs may time out; supervisor emits `job_stuck` |

The queue does **not** implement pushback (rejecting pushes). Backpressure is
**detected** by the Queue Supervisor (`src/platform/supervisor/queue_supervisor.py`)
and surfaced as observability events. Control decisions (scale up, drain, alert)
are made by the supervisor layer.

---

## Subscription Model

- **S5 (agents + workflows)** subscribes to S4 events via the event
  substrate. It never owns or operates the transport directly.
- The queue is owned by S4. S5 receives event callbacks.
- `Channel`s are registered in a `ChannelRegistry` (name → `Channel` adapter).
- Workers call `channel.normalize()` to convert `InboundChannelMessage` into
  canonical job payloads, then route responses via `ChannelRegistry`.

---

## Trigger Sources

| Source | Description | Example |
|--------|-------------|---------|
| **User-initiated** | Inbound from CLI, HTTP, WebSocket, webhook, Slack, email | `python -m s4.daemon --input "deploy"` |
| **System-initiated** | Cron-like scheduled triggers | Periodic health check jobs |
| **Workflow-internal** | Jobs enqueued by other jobs during execution | Pipeline continuation jobs |

---

## Delivery Guarantees

| Guarantee | Implementation |
|-----------|---------------|
| **At-least-once** | Lease semantics: a popped job stays in-flight until acked. If the worker crashes, the lease expires and the job is requeued. |
| **FIFO ordering** | Within a single queue, push order is preserved on pop. No cross-queue ordering guarantees. |
| **No duplication** | InMemoryQueue ensures a popped item is not visible to other consumers. RedisListQueue uses RPOPLPUSH atomicity. |

---

## Related Documents

- [CONTROL_PLANE.md](CONTROL_PLANE.md) — Job lifecycle orchestration
- [WORKER_POOL.md](WORKER_POOL.md) — Worker pop semantics
- [BOUNDARIES.md](BOUNDARIES.md) — Stratum isolation rules
- [CHANNELS.md](CHANNELS.md) — Ingress normalization pipeline
