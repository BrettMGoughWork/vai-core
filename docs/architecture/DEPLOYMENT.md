# Deployment — Local, Container, and Cloud

**Purpose:** Deployment strategies for the vai-core runtime. Defines the
entrypoint, lifecycle, and configuration model for each target environment.

File: `src/platform/deployment/__init__.py`

---

## Target Selection

```python
run_target("local")      # → _run_local()
run_target("container")  # → _run_container()
run_target("cloud")      # → DeploymentError (deferred)
```

---

## Local Deployment

**Command:** `python -m s4.daemon`

```
STARTING
    │  load config, init subsystems
    ▼
RUNNING
    │  KeyboardInterrupt (Ctrl+C)
    ▼
DRAINING
    │  stop workers, ack in-flight jobs
    ▼
SHUTDOWN
```

| Feature | Detail |
|---------|--------|
| **Queue** | In-process `InMemoryQueue` (FIFO) |
| **Storage** | Local filesystem |
| **Logging** | stdout/stderr |
| **External deps** | Zero — no Redis, no Postgres, no Docker required |
| **Shutdown** | `KeyboardInterrupt` (SIGINT) |

---

## Container Deployment

**Base image:** Python 3.12-slim (Debian-based).

### Dockerfile Layout

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local /usr/local
COPY src/ src/
EXPOSE 8080
ENTRYPOINT ["python", "-m", "s4.daemon"]
```

### Container Lifecycle

```
python -m s4.daemon
    │  PID 1
    ▼
SIGTERM handler installed
    │
    ▼
STARTING → RUNNING → DRAINING → SHUTDOWN
                         ▲
                    SIGTERM received
```

- PID 1 with proper SIGTERM handler (no zombie reaping needed — Python
  3.12-slim handles this).
- All log output to stdout/stderr (no log files inside container).
- In-memory queue (default) — no external dependencies.

### Build and Run

```bash
# Build
docker build -t vai-core:latest .

# Run
docker run --rm -it \
  -e S4LOGGINGLEVEL=debug \
  -e S4QUEUEBACKEND=in_memory \
  -p 8080:8080 \
  vai-core:latest
```

---

## Cloud Deployment (Deferred)

Cloud deployment is **acknowledged but deferred** — no code changes are needed.
The container image + environment variable configuration model is the cloud
deployment contract.

### Future Cloud Entrypoints

| Provider | Entrypoint | Infrastructure Required |
|----------|-----------|------------------------|
| AWS | ECS/Fargate task def | Redis (ElastiCache), S3 (job store) |
| GCP | Cloud Run service | Redis (Memorystore), GCS |
| Azure | Container Instances | Redis Cache, Blob Storage |

No vai-core code changes needed — only container image + config tuning.

---

## Configuration via Environment Variables

File: `src/platform/config/config_system.py`

Config is a 4-layer merge:

```
Defaults → YAML file → Env vars → Runtime overrides
```

### Env Var Pattern

Pattern: `S4_{SECTION}_{FIELD}` (uppercase, underscore-separated).

| Env Var | Config Key | Example |
|---------|------------|---------|
| `S4LOGGINGLEVEL` | `logging.level` | `debug` |
| `S4QUEUEBACKEND` | `queue.backend` | `in_memory` |
| `S4QUEUEREDISURL` | `queue.redis_url` | `redis://localhost:6379/0` |
| `S4SUPERVISORCHECKINTERVAL` | `supervisor.check_interval` | `10.0` |
| `S4WORKERPOOLCONCURRENCY` | `worker_pool.concurrency` | `4` |

Nested sections are flattened: `S4WORKERPOOLCONCURRENCY` →
`config["worker_pool"]["concurrency"]`.

### Runtime Immutability

`S4Config` is read-only — `TypeError` on mutation. Config is frozen at startup.

---

## Related Documents

- [CONTROL_PLANE.md](CONTROL_PLANE.md) — Daemon lifecycle integration
- [EVENT_SUBSTRATE.md](EVENT_SUBSTRATE.md) — Queue backend selection
- [OBSERVABILITY.md](OBSERVABILITY.md) — Logging/metrics in container vs local
- [BOUNDARIES.md](BOUNDARIES.md) — Config immutability rules
