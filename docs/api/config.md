# Configuration API — S4.9.1

**Module:** `src.platform.config.config_system`

The configuration system loads, validates, and exposes read-only configuration
to all S4 components. Every value has a schema-defined default — S4 can start
with zero configuration files and still operate correctly.

---

## `load_config()`

```python
def load_config(
    config_file: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> S4Config:
```

Load configuration from four ordered layers. Later layers override earlier ones.

### Loading Order

| Priority | Layer | Source | Example |
|---|---|---|---|
| 1 (base) | **Defaults** | `SCHEMA` hardcoded dict | `logging.level = "info"` |
| 2 | **YAML file** | Path to `.yaml`/`.yml` | `config_file="s4.yaml"` |
| 3 | **Env vars** | `S4_`‑prefixed variables | `S4LOGGINGLEVEL=debug` |
| 4 (winner) | **Overrides** | Dict with dotted keys | `{"workers.count": 8}` |

### Args / Returns / Raises

| Category | Detail |
|---|---|
| `config_file` | Optional path to a YAML config file. Only schema-known sections are read; unrelated keys (e.g. `llm`) are silently ignored. |
| `overrides` | Optional dict mapping dotted keys (e.g. `"auth.enabled"`) to values. Section+field format required — single-part keys raise `ConfigError`. |
| Returns | An immutable `S4Config` instance. |
| Raises `ConfigError` | If the file cannot be read, parsed, or is not a mapping. |
| Raises `UnknownKeyError` | If any key is not in the schema. |
| Raises `ConfigValidationError` | If a value fails type or range validation. |

### Example

```python
from src.platform.config.config_system import load_config

cfg = load_config(
    config_file="./s4.prod.yaml",
    overrides={"workers.count": 16},
)
```

---

## `S4Config` — Immutable Configuration Object

```python
class S4Config:
    def __init__(self, data: dict[str, Any]) -> None: ...
    def get(self, key: str) -> Any: ...
    def to_dict(self) -> dict[str, Any]: ...
```

**Immutability guarantee:** After construction, `S4Config` raises `TypeError`
on any attribute set or delete operation. The config is safe to share across
threads without locking.

### `get(key)`

Access values via dotted key paths:

```python
cfg.get("logging.level")        # "info"
cfg.get("workers.count")        # 4
cfg.get("alerts.transports")    # ["none"]
```

Raises `KeyError` if the key is unknown.

### `to_dict()`

Return a deep copy of the full configuration as a plain dict:

```python
all_config = cfg.to_dict()
```

Useful for serialization, CLI display, or debugging. The returned dict is a
copy — mutations to it do **not** affect the original `S4Config`.

---

## Schema Structure

The schema defines seven top-level sections:

### `logging`

| Field | Type | Default | Valid Values |
|---|---|---|---|
| `level` | `str` | `"info"` | `"debug"`, `"info"`, `"warning"`, `"error"`, `"critical"` |

### `metrics`

| Field | Type | Default | Valid Values |
|---|---|---|---|
| `enabled` | `bool` | `True` | — |
| `exporter` | `str` | `"stdout"` | `"none"`, `"stdout"`, `"prometheus"` |

### `queues`

| Field | Type | Default | Valid Values |
|---|---|---|---|
| `defaultdepthlimit` | `int` | `1000` | — |

### `workers`

| Field | Type | Default | Valid Values |
|---|---|---|---|
| `count` | `int` | `4` | — |
| `heartbeatintervalms` | `int` | `5000` | — |
| `heartbeattimeoutms` | `int` | `15000` | — |

### `alerts`

| Field | Type | Default | Valid Values |
|---|---|---|---|
| `transports` | `list[str]` | `["none"]` | `"slack"`, `"smtp"`, `"file"`, `"none"` |

### `auth`

| Field | Type | Default | Valid Values |
|---|---|---|---|
| `enabled` | `bool` | `False` | — |
| `token` | `str` | `""` | — |

### `rate_limit`

| Field | Type | Default | Valid Values |
|---|---|---|---|
| `enabled` | `bool` | `False` | — |
| `maxrequestsper_minute` | `int` | `60` | — |

---

## Environment Variable Mapping

Environment variables follow a strict naming convention:

```
S4 + <SECTION_NAME> + <FIELD_NAME>
```

Both section and field names are uppercase with underscores and dots removed.

### Mapping Table

| Env Variable | Target |
|---|---|
| `S4LOGGINGLEVEL` | `logging.level` |
| `S4METRICSENABLED` | `metrics.enabled` |
| `S4METRICSEXPORTER` | `metrics.exporter` |
| `S4QUEUESDEFAULTDEPTHLIMIT` | `queues.defaultdepthlimit` |
| `S4WORKERSCOUNT` | `workers.count` |
| `S4WORKERSHEARTBEATINTERVALMS` | `workers.heartbeatintervalms` |
| `S4WORKERSHEARTBEATTIMEOUTMS` | `workers.heartbeattimeoutms` |
| `S4ALERTSTRANSPORTS` | `alerts.transports` |
| `S4AUTHENABLED` | `auth.enabled` |
| `S4AUTHTOKEN` | `auth.token` |
| `S4RATELIMITENABLED` | `rate_limit.enabled` |
| `S4RATELIMITMAXREQUESTSPER_MINUTE` | `rate_limit.maxrequestsper_minute` |

### Value Parsing Rules

- **`bool`** — accepts `"true"` or `"false"` (case-insensitive).
- **`int`** — parsed with `int()`. Non-integer values raise `ConfigValidationError`.
- **`str`** — trimmed and validated against `valid_values` if defined.
- **`list`** — comma-separated; each item validated against `item_valid_values`.

---

## YAML Config File Format

Only sections matching the schema are loaded. Unrelated keys are silently
ignored, allowing co-location with other configuration:

```yaml
# s4.yaml
logging:
  level: debug

metrics:
  enabled: true
  exporter: stdout

workers:
  count: 8
  heartbeatintervalms: 5000

auth:
  enabled: true
  token: "s4-prod-token"

# Unrelated config — silently ignored
llm:
  model: gpt-4
  temperature: 0.7
```

---

## Error Types

| Exception | Raised When |
|---|---|
| `ConfigError` | File not found, not a file, unparseable, or override format wrong |
| `UnknownKeyError` | Key path includes a key not in the schema |
| `ConfigValidationError` | Value has wrong type, is outside valid_values, or parse failure |

All three inherit from `ConfigError`, so a single `except ConfigError` catches
all configuration failures.

---

## Invariants

1. **Deterministic** — `load_config()` with the same inputs always produces
   the same config. No randomness, no time dependence.
2. **Immutable output** — `S4Config` cannot be modified after construction.
3. **Type-safe** — every value is validated against its schema-defined type.
4. **Fail-fast** — any unknown key or invalid value raises immediately.
5. **Env var wins over file** — environment variables always override file
   values, making container deployments predictable.
