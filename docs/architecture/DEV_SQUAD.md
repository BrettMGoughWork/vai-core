# DevSquad — Multi-Agent Sprint Factory

DevSquad is a **declarative multi-agent sprint pipeline** built on the vai-core runtime. Drop in a north-star description, and DevSquad orchestrates a team of agents (PM, Architect, Engineer, Reviewer) to produce a complete implementation.

> **Status:** Early development — the pipeline runs end-to-end, but iteration limits and edge-case handling are still being tuned.

---

## Architecture

### Pipeline Flow

```
Human (north-star) → Interview → PRD → Architecture → Delivery Plan → Engineer → Council Review → Output
```

| Step | Agent | Produces | Description |
|------|-------|----------|-------------|
| **1. Interview** | `devsquad-interviewer` | Sprint params (JSON) | Collects north-star from user (free text or inbox `.md` file). Confirms scope, generates `project_id` and requirements. |
| **2. PRD** | `agent-pm` | `prd.md` | Product Requirements Document — detailed feature breakdown. |
| **3. Architecture** | `agent-architect` | `solution.md` | Solution design — technology choices, component architecture, data model, module breakdown. |
| **4. Delivery Plan** | `agent-architect` | `delivery_plan.json` | Ordered task blocks (each: description, files to create/modify, acceptance criteria). |
| **5. Implementation** | `agent-engineer` | `implementation.md` | Writes all code files, runs tests, verifies build. |
| **6. Council Review** | `agent-pm` + `agent-architect` + `agent-engineer` | Review output | Council panellists critique the implementation; adjudicator summarises. |

All six steps run **sequentially in-process** via `PipelineDriver`. The pipeline is kicked off as a single CLI subprocess.

### File Layout

```
projects/
  inbox/                         # Drop north-star .md files here
  <project-id>/
    prd.md                       # Product requirements
    solution.md                  # Architecture / solution design
    delivery_plan.json           # Ordered task blocks
    implementation.md            # Engineer's summary of what was built
    metadata.json                # Pipeline execution metadata
    metadata/                    # Per-stage metadata (prd, solution, delivery_plan)
    <source files...>            # Generated project code
```

### Pipeline Driver

`PipelineDriver` (`src/devsquad/pipeline_driver.py`) drives workflows synchronously:

1. Starts workflows matched to the `sprint.init` event
2. Steps through each workflow (LLM calls, tool execution)
3. Intercepts `publish_event` tool results to chain to the next workflow
4. Prints JSON progress lines (`{"progress": "workflow_completed", ...}`) so the CLI primitive's sliding-wall timeout stays alive

The driver runs all workflows in a **single process** — no async supervisor, no S4 jobs. This keeps latency low and simplifies debugging.

---

## Usage

### Quick start

```bash
# Interactive mode — type your north-star description
python -m src.devsquad interview

# Or provide a JSON payload (non-interactive, for automation / primitive use)
python -m src.devsquad interview --json input.json

# With auto-confirm (skips the "looks good?" prompt)
python -m src.devsquad interview --json input.json --confirm
```

### JSON input format

```json
{
  "north_star": "Build a telnet-based MUD set in the Forgotten Realms...",
  "auto_confirm": true,
  "project_id": "forgotten-realms-mud",
  "file_path": "sprints/forgotten-realms-mud/requirements.md"
}
```

Only `north_star` is required. `auto_confirm` skips the confirmation prompt. `project_id` overrides auto-generation. `file_path` optionally links a requirements file.

### Inbox (file-based north star)

Drop a `.md` file in `projects/inbox/`, then:

```bash
python -m src.devsquad interview
# → Type the filename when prompted (e.g., "forgotten-realms-mud.md")
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEVSQUAD_PROJECTS_ROOT` | `./projects` | Root directory for all sprint projects |

### Agent Definitions

Agent personas and capabilities are declared in `config/agents/`:

| File | Agent |
|------|-------|
| `devsquad-interviewer.yaml` | Sprint interviewer |
| `agent-pm.yaml` | Product Manager |
| `agent-architect.yaml` | Architect |
| `agent-engineer.yaml` | Engineer |

### Workflow Definitions

Six workflows in `config/workflows/` — one per pipeline stage:

| File | Workflow |
|------|----------|
| `devsquad-bootstrap.yaml` | Project structure creation |
| `devsquad-architecture.yaml` | Solution architecture |
| `devsquad-delivery-plan.yaml` | Delivery plan from solution |
| `devsquad-implementation.yaml` | Engineer implementation |
| `devsquad-review.yaml` | Council review |
| `devsquad-acceptance.yaml` | Acceptance checks |

### Prompt Templates

Templated prompts in `config/prompts/`:

| File | Purpose |
|------|---------|
| `devsquad-pm-prd.yaml` | PM generates PRD |
| `devsquad-architect-solution.yaml` | Architect creates solution design |
| `devsquad-architect-delivery-plan.yaml` | Architect breaks solution into blocks |
| `devsquad-engineer-implement.yaml` | Engineer implements all blocks |
| `devsquad-reviewer-council.yaml` | Council review panel |

---

## How It Works (Internally)

### Subprocess Pipeline

When triggered from the chat (via the `devsquad-interview` CLI primitive), the entire pipeline runs as a **single subprocess**:

```
Chat → CompositionRoot (timeout safety net) → subprocess (python -m src.devsquad interview --json)
                                                                     │
                                                              PipelineDriver
                                                              (6 workflows,
                                                               sliding-wall
                                                               timeout)
```

The sliding-wall timeout in `CLIPrimitive` keeps the subprocess alive as long as it produces output. Each completed workflow emits a JSON progress line to stdout, resetting the timeout window. If the subprocess goes silent for 10 minutes, it is killed as a safety net.

### Agentic Step (Engineer Implementation)

The engineer uses a **tool-calling loop** (`execute_agentic_step` in `src/devsquad/agentic_step.py`) rather than the workflow engine's fixed steps. This allows the LLM to dynamically decide which tools to call and iterate until all blocks are implemented.

Flow:
1. System prompt + delivery plan + solution architecture are sent to the LLM
2. LLM responds with tool calls (write_file, read_file, execute_command, etc.)
3. Each tool call is executed and the result is fed back as a new message
4. When the LLM produces a text-only response (no tool calls), the loop ends
5. A fallback summary is generated if the iteration limit is reached

The iteration limit (`_MAX_TOOL_ITERATIONS = 50`) prevents infinite loops. The engineer prompt includes instructions to stop calling tools and produce a final report once all blocks are implemented.

---

## Known Limitations

- **Iteration limit tuning** — engineer iteration limit (50) may need adjustment for large projects
- **No persistence** — pipeline state is in-memory; a crash mid-pipeline restarts from scratch
- **Single process** — all workflows run in one process; parallelism is not yet supported
- **No real-time streaming** — output arrives in one batch when the pipeline finishes
- **Chat integration via CLI primitive** — the pipeline runs as a subprocess, not directly in the agent's tool loop
