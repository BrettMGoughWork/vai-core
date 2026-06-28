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
  "file_path": "sprints/forgotten-realms-mud/requirements.md",
  "reference_doc": "path/to/detailed-spec.md"
}
```

Only `north_star` is required. `auto_confirm` skips the confirmation prompt. `project_id` overrides auto-generation. `file_path` optionally links a requirements file. `reference_doc` provides a detailed markdown spec that the interview agent reads and asks follow-ups about (see [Reference Document Support](#reference-document-support)).

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

### Code Verification Step

Starting in step 5 of the engineer prompt, the engineer is required to **verify the generated code loads without import errors** before running the test suite. This is implemented as a direct instruction in the prompt:

> *"Verify the code loads without import errors. Run `python -c 'from your_package import ...'` or equivalent syntax check. Fix any missing dependencies or import issues before proceeding."*

This addresses a common failure mode where the LLM generates code that references modules or dependencies that don't exist yet, causing the test suite to fail on import errors rather than actual logic issues. The verification runs **before** unit tests (step 6), ensuring a clean import baseline.

---

## Reference Document Support

When launching a sprint via JSON input mode, you can provide a **reference document** — a detailed markdown spec that the interview agent reads alongside the north star. The agent explicitly asks follow-up questions about anything unclear in the reference doc.

### JSON input with reference doc

```json
{
  "north_star": "Build a telnet-based MUD set in the Forgotten Realms...",
  "reference_doc": "path/to/detailed-spec.md",
  "auto_confirm": true,
  "project_id": "forgotten-realms-mud"
}
```

The `reference_doc` field points to a markdown file that is loaded and injected into the interview agent's context as supplementary requirements. The agent is instructed to:

1. Read and understand the reference document
2. Ask follow-up questions about anything ambiguous
3. Merge the reference spec with the north star into the final sprint requirements

If no `reference_doc` is provided, the interview proceeds with only the north star (existing behaviour).

### Reference doc with interactive mode

When running interactive mode, the interview agent prompts for an optional reference document path at the start of the session.

---

## Iterative Sprints

DevSquad supports **iterative sprints** — running a second (or third, etc.) sprint on an existing project to build on top of previous work.

### How it works

1. When `kickoff_sprint()` detects that the project directory already exists, it reads the existing artifacts (`prd.md`, `solution.md`, `delivery_plan.json`)
2. It constructs a `sprint_context` blob describing the current project state:
   - What stage the project is at (what artifacts exist)
   - The existing PRD, solution design, and delivery plan
   - Which iteration this is (iteration number)
3. This `sprint_context` is injected into the **PM, Architect, and Engineer** prompts so each agent is aware of prior work
4. Agents are instructed to build on — not overwrite — the existing project

### Iteration lifecycle

```
Iteration 1 (fresh project):
  PM creates PRD → Architect designs solution → Engineer implements

Iteration 2+ (existing project):
  PM reads existing PRD, updates/enhances → Architect refines solution → 
  Engineer implements new features on top of existing codebase
```

### Interactive UX

When running in **interactive mode** and the extracted `project_id` matches an existing project directory, the system prompts:

```
  [⏺] Existing project found: ./projects/forgotten-realms-telnet-mud
  Iterate on this project (build on top of existing work)? (Y/n):
```

- **Yes** (default) — the sprint runs as iteration 2+. All agents receive context about prior work.
- **No** — a fresh `project_id` is generated with an incrementing version suffix (e.g. `forgotten-realms-telnet-mud-v2`) and the sprint starts from scratch.

In **JSON (non-interactive) mode**, the existing behaviour applies — if the `project_id` matches an existing directory, it always iterates. To start fresh in JSON mode, provide a different `project_id`.

### Context injection

The `sprint_context` is passed through the entire workflow chain via event payloads, ensuring every agent has visibility into prior iterations. The prompt templates use the `{sprint_context}` placeholder which is resolved at runtime by the pipeline driver.

### Limitations

- Iteration detection is simple — it checks if the project directory exists. Future versions could track iteration count in metadata.
- The sprint context is a static text blob. There's no diff or change-tracking between iterations.
- Agents must be trusted to respect prior work rather than overwrite it — enforcement is prompt-based.

---

## Known Limitations

- **Iteration limit tuning** — engineer iteration limit (50) may need adjustment for large projects
- **No persistence** — pipeline state is in-memory; a crash mid-pipeline restarts from scratch
- **Single process** — all workflows run in one process; parallelism is not yet supported
- **No real-time streaming** — output arrives in one batch when the pipeline finishes
- **Chat integration via CLI primitive** — the pipeline runs as a subprocess, not directly in the agent's tool loop
