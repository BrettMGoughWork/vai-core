# vai-core

`vai-core` is a lightweight, layered Python agent runtime focused on clear boundaries, explicit contracts, and testable execution.

This is a "lessons-learned" project from a previous agent runtime that evolved naturally, and hit a complexity ceiling. This is an attempt to create a plan with invariants, and to ensure a more modular approach to reach a greater outcome.

Community contribution very welcome.

## Quick start

```bash
# 1) Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 2) Install dependencies
pip install -r requirements.txt

# 3) Run the CLI runtime
python main.py

# 4) Run tests
uv run --with pytest --with python-dotenv pytest -q
```

Create a `.env` file in the repo root:

```env
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

## Runtime flow (current)

`main.py` builds an `AgentRuntime` with:
1. LLM alias resolution from `config/llms.yaml`
2. `DeepSeekClient` + `LLMTransport`
3. `AgentConfig` with allowed tools/categories/side effects

`AgentRuntime.run()` executes a bounded multi-step loop:
1. Build prompt from `ConversationState`
2. Call LLM through transport
3. Select/govern tool
4. Execute tool
5. Classify outcome (`SUCCESS`, `RECOVERABLE`, `NOOP`, `FATAL`)
6. Stop on success/fatal/step limit/timeouts

## Recent updates

- Added loop policy controls in `LoopPolicy`: `max_steps`, `max_wall_time`, `max_errors`, `max_fatals`, `per_step_timeout`.
- Added per-step timeout and wall-time protection in `AgentRuntime`.
- Added step trace capture (`StepTrace`) to record each loop step summary/outcome/error.
- Added executor contract and single-skill executor (`ExecutionResult`, `SingleSkillExecutor`).
- Added/expanded structured logging with `Logger`, `StdoutLogger`, and `StructuredLogger`.
- Added integration coverage for the CoreStep pipeline and expanded unit tests across runtime, planning, execution, and config.
- Updated LLM aliases to include `deepseek-chat` and `deepseek-reasoner` in `config/llms.yaml`.

## Repository layout

```text
config/                    # Runtime/model config
main.py                    # CLI entrypoint
src/
  core/                    # Agent runtime, planning, core skills, LLM transport/types
  execution/               # Execution engine, contract, single-skill executor
  governance/              # Tool selection and guardrails
  observability/           # Structured logging
  policy/                  # Runtime policy hooks
  skills/                  # Skill ranking/filtering and builtins
  telemetry/               # Telemetry hooks
tests/
  unit/                    # Unit tests
  integration/             # Integration tests
```

## Testing

`pytest.ini` scopes discovery to `tests/`.

Run all tests:

```bash
uv run --with pytest --with python-dotenv pytest -q
```
