# vai-core

A minimal, layered agent runtime built around deterministic boundaries, canonical actions, and introspected skills.

## Quick Start

```bash
# Install dependencies
uv sync

# Run the runtime entrypoint
uv run python main.py

# Run test suite
uv run --with pytest --with python-dotenv pytest -q
```

## Directory Structure

```
src/
├── core/              # Core execution loop and utilities
│   ├── agent/         # Agent config, state, step, and runtime
│   ├── loop.py        # CoreLoop: one LLM call → one action
│   ├── config/        # Config loading (JSON + env overrides)
│   ├── skills/        # Skill introspection and validation
│   │   ├── base.py    # BaseSkill: wrapper with validation pipeline
│   │   ├── canonical.py  # Canonicalisation rules
│   │   ├── validator.py  # Structural & semantic validation
│   │   ├── schema.py     # Schema inference from handlers
│   │   └── registry.py   # Skill registry
│   └── llm/           # LLM transport layer
│       ├── transport.py  # Provider-agnostic LLM interface
│       └── types.py      # Response types
├── transport/         # External service clients (reserved)
├── governance/        # Action shape validation & canonicalisation
├── execution/         # Skill execution and routing
├── policy/            # Runtime constraints (allowed tools, size limits)
├── caching/           # Action fingerprinting and caching
├── observability/     # Structured logging
├── telemetry/         # Metrics and tracing
└── util/              # Shared helpers

config/
├── default.json       # Default LLM and policy settings
├── llms.yaml          # LLM aliases and model mappings
└── agents.yaml        # Agent definitions

tests/
├── test_agent_e2e.py              # End-to-end runtime flow with fake LLM
├── test_core_agent_runtime.py     # AgentRuntime behavior
├── test_core_agent_corestep.py    # Single-step stateful execution
├── test_core_agent_state.py       # ConversationState prompt/history logic
├── test_core_llm_transport.py     # Transport layer tests
└── test_core_*.py                 # Other layer-specific unit tests

main.py               # Entry point: initializes runtime + transport
```

## Key Concepts

### CoreLoop

The heartbeat of vai-core. Processes one user input → produces one action → executes it.

```python
runtime = create_runtime()
result = runtime.run("add 1 and 2")
```

Flow:
1. **Policy** validates user input
2. **LLM** generates raw action
3. **Governance** canonicalises and validates action shape
4. **Cache** checks for prior identical actions
5. **Executor** routes to skill and executes
6. **Telemetry** records metrics

### Skills

Pure Python functions wrapped in `BaseSkill`. No side effects, no LLM calls.

```python
skill = BaseSkill(
    name="add",
    description="Add two numbers",
    handler=lambda a, b: a + b,
)

# BaseSkill.run() automatically:
# - Canonicalises arguments (trim strings, coerce types)
# - Validates structural shape
# - Validates semantic constraints
# - Executes the handler
result = skill.run(a=" 5 ", b="3")  # → 8
```

### LLMTransport

Vendor-agnostic interface for LLM calls.

```python
transport = LLMTransport(client)
response = transport.call(
    prompt="generate a plan",
    tools=[skill1.spec, skill2.spec],
    model="deepseek-chat",
)
```

## Design Principles

- **Tight separation of concerns**: Each layer has one job.
- **Small layers**: Fewer than ~200 lines per module.
- **Simplicity**: Prefer simple implementations over feature-rich.
- **Tight boundaries**: Clear input/output contracts.
- **Highly testable**: No global state, pure functions where possible.
- **Safer mutations**: Validation before execution.

## Environment Setup

Create a `.env` file in the repo root:

```env
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

`DEEPSEEK_API_KEY` is read by `DeepSeekClient` at runtime.

## Testing

All layers have focused unit tests:

- `test_core_skills_canonical.py` — canonicalisation rules
- `test_core_skills_validator.py` — structural validation
- `test_core_skills_schema.py` — schema inference
- `test_core_skills_base.py` — skill execution
- `test_core_llm_deepseek_client.py` — DeepSeek provider client
- `test_core_llm_transport.py` — LLM transport
- `test_agent_e2e.py` — full stack integration

`pytest.ini` scopes discovery to `tests/`.

Run all: `uv run --with pytest --with python-dotenv pytest -q`
