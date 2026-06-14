# Channels — Ingress Adapter Model

**Purpose:** Ingress adapters that normalise external events into
`InboundChannelMessage` — the canonical inbound envelope for Stratum-4.
Channels are pure plumbing: they know nothing about workflows, agents, or jobs.

---

## Architecture

```
 External Event
      │
      ▼
  ┌──────────┐   receive()    ┌──────────────────┐  normalize()   ┌───────┐
  │ Channel  │ ─────────────→ │InboundChannelMsg │ ──────────────→ │ Event │
  │ Adapter  │                │(channel, sender,  │               │Substr.│
  │ (CLI/WS/ │                │ payload, timestamp)│               │       │
  │  Mail/…) │                └──────────────────┘               └───────┘
  └──────────┘
```

### Channel Protocol

File: `src/platform/runtime/channels/base.py`

```python
class Channel(Protocol):
    def receive(self, raw_input: Any) -> InboundChannelMessage: ...
    def normalize(self, message: InboundChannelMessage) -> dict: ...
    def send(self, message: dict) -> dict: ...
```

### InboundChannelMessage

```python
@dataclass(frozen=True)
class InboundChannelMessage:
    channel: str                # "cli", "web", "ws", ...
    sender: str | None          # user identity
    payload: dict[str, Any]     # the user's payload
    timestamp: float            # Unix timestamp
```

---

## Channel Types

### CLI Channel (`src/platform/runtime/channels/cli.py`)

| Aspect | Detail |
|--------|--------|
| **Purpose** | Convert raw CLI text input into events |
| **Input** | `{"text": "...", "sender": "..."}` |
| **Normalized** | `{"input": "...", "metadata": {"channel": "cli", "sender": "..."}}` |
| **Lifecycle** | Pure logic — no argparse, no terminal IO |
| **Failure** | `TypeError` on non-dict, `ValueError` on missing text |
| **Backpressure** | N/A (single-threaded stdin read) |
| **Config** | None (stateless) |

### HTTP/Web Channel (`src/platform/runtime/channels/web.py`)

| Aspect | Detail |
|--------|--------|
| **Purpose** | Structured HTTP JSON bodies → events |
| **Input** | `{"input": "...", "sender": "...", "metadata": {...}}` |
| **Normalized** | `{"input": "...", "metadata": {"channel": "web", "sender": "..."}}` |
| **Lifecycle** | Pure logic — no FastAPI, no routing |
| **Failure** | `TypeError`/`ValueError` on malformed body |
| **Backpressure** | N/A (per-request handler) |
| **Config** | None (stateless) |

### WebSocket Channel (`src/platform/runtime/channels/ws.py`)

| Aspect | Detail |
|--------|--------|
| **Purpose** | WebSocket frames → events |
| **Input** | `{"text": "...", "sender": "...", "message_type": "text"}` |
| **Normalized** | `{"input": "...", "metadata": {"channel": "ws", "sender": "...", "message_type": "text"}}` |
| **Lifecycle** | Pure logic — no event loop, no WS server |
| **Failure** | `TypeError`/`ValueError` on frame validation |
| **Backpressure** | N/A (per-frame handler) |

### Webhook Channel (`src/platform/runtime/channels/webhook.py`)

| Aspect | Detail |
|--------|--------|
| **Purpose** | Accept POST bodies from external systems (WhatsApp, GitHub, etc.) |
| **Input** | `{"source": "github", "payload": {...}, "sender": "..."}` |
| **Normalized** | `{"input": {...}, "metadata": {"channel": "webhook", "source": "github", "sender": "..."}}` |
| **Failure** | `TypeError`/`ValueError` on missing source or payload |
| **Supports** | whatsapp, telegram, github, stripe, twilio, slack, discord, generic |

---

## Alert Transport Channels

These are outbound-only — they deliver S4 alerts to external systems.

### Slack Channel (`src/platform/runtime/channels/slack.py`)

| Aspect | Detail |
|--------|--------|
| **Purpose** | Slack Events API inbound + outbound |
| **Inbound** | `{"text": "...", "sender": "U12345", "channel": "C67890", "team": "T11111"}` |
| **Outbound** | Slack-compatible webhook POST body with Block Kit formatting |

### Mail Channel (`src/platform/runtime/channels/mail.py`)

| Aspect | Detail |
|--------|--------|
| **Purpose** | Email inbound + outbound (SMTP/IMAP) |
| **Inbound** | `{"from": "a@b.com", "to": "bot@vai", "subject": "Deploy", "body": "..."}` |
| **Outbound** | SMTP-compatible send dict with to/subject/body |

---

## Pluggability

Adding a new channel requires **no S4 core changes**:

1. Implement the `Channel` protocol (receive/normalize/send).
2. Register in `ChannelRegistry` under a unique name.
3. Done.

```python
class CustomChannel:
    def receive(self, raw_input: Any) -> InboundChannelMessage: ...
    def normalize(self, message: InboundChannelMessage) -> dict: ...
    def send(self, message: dict) -> dict: ...

registry = ChannelRegistry()
registry.register("custom", CustomChannel())
```

---

## Design Constraints

- Channels do **not** know about workflows or agents — they are pure plumbing.
- All channel logic is pure (deterministic, no IO, no side effects).
- Channels are registered at startup in the composition root.
- The `ChannelRegistry` is a simple dict lookup — no routing, no logic.

---

## Related Documents

- [EVENT_SUBSTRATE.md](EVENT_SUBSTRATE.md) — Event bus integration
- [OBSERVABILITY.md](OBSERVABILITY.md) — Logging correlation IDs
- [WORKER_POOL.md](WORKER_POOL.md) — Handler dispatch
- [BOUNDARIES.md](BOUNDARIES.md) — Pluggability without core changes
