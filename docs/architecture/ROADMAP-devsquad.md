# DevSquad Sprint Pipeline — Implementation Roadmap

**Status:** Draft &mdash; Target: DeepSeek‑Flash implementable  
**Audience:** DeepSeek‑Flash (execution model) consuming this as spec  
**Runtime:** vai‑core primitives (workflows, job families, agents, events, patterns, councils)

---

## Table of Contents

1. [Overview of the DevSquad Pipeline](#1-overview-of-the-devsquad-pipeline)
2. [Event‑Driven Workflow Skeleton](#2-event‑driven-workflow-skeleton)
3. [Job Family Specifications](#3-job-family-specifications)
4. [Artifact Schemas](#4-artifact-schemas)
5. [Project Folder Structure](#5-project-folder-structure)
6. [Agent Prompt Templates](#6-agent-prompt-templates)
7. [Execution Flow Example](#7-execution-flow-example)
8. [Implementation Steps for DeepSeek‑Flash](#8-implementation-steps-for-deepseek‑flash)

---

## 1. Overview of the DevSquad Pipeline

### 1.1 What It Is

The DevSquad pipeline is a **sprint‑based software delivery system** that automates the full lifecycle of a feature from requirements to acceptance. It uses three core AI roles — **PM**, **Architect**, and **Engineer** — plus a **Client/HITL** (Human‑in‑the‑Loop) role for acceptance and course‑correction. Each stage produces a versioned artifact under `/projects/<project-id>/`. Transitions between stages are driven by **events** published to the `EventBus`, picked up by the `TriggerRouter`, and executed as **workflow steps** in the `WorkflowEngine`.

### 1.2 The Trio Roles

| Role | Agent ID | Responsibility | Primary Artifacts |
|------|----------|----------------|-------------------|
| **PM** | `agent-pm` | Requirements gathering, user stories, acceptance criteria, sprint scope | `prd.md` |
| **Architect** | `agent-architect` | System design, technology choices, delivery planning, code review | `solution.md`, `delivery_plan.json`, `review.md` |
| **Engineer** | `agent-engineer` | Implementation against delivery plan, unit tests, self-review | `src/`, `tests/`, `implementation.md` |
| **Client/HITL** | `agent-client` | Acceptance testing, feedback, go/no-go decisions | `acceptance.md`, `feedback.json` |

### 1.3 The Sprint Lifecycle

```
PRD ──▶ Architecture ──▶ Delivery Plan ──▶ Implementation ──▶ Review ──▶ HITL Acceptance
  │            │                │                  │              │              │
  │   PM       │   Architect    │   Architect      │   Engineer   │  PM+Arch     │  Client
  │   writes   │   designs      │   breaks down    │   codes      │  review      │  accepts
  │            │                │                  │              │              │
  └─ Event ───┴── Event ───────┴── Event ─────────┴── Event ─────┴── Event ─────┘
     prd.        solution.         delivery_plan.     impl.          review.        acceptance.
     completed   completed         completed          completed      completed       completed
```

Each lifecycle stage:
1. Waits for its trigger event
2. Dispatches a job to the appropriate job family
3. The agent produces an artifact at a known path
4. On completion, emits the next event in the chain

### 1.4 How Events Drive Transitions

Every stage boundary is an **event**. The `TriggerRouter` maps each event to a workflow definition. The workflow engine executes steps sequentially (LLM calls, tool executions, sub‑workflows, user‑input waits). When a step completes, the engine checks `transitions` to determine the next step. The final step of each stage publishes the next lifecycle event.

```
EventBus.publish(event) ──▶ TriggerRouter.handle_event(event)
                                   │
                                   ▼
                            WorkflowEngine.run(workflow_def, context)
                                   │
                                   ▼
                            JobQueue.submit(job_family, payload)
                                   │
                                   ▼
                            Agent produces artifact at /projects/<id>/...
                                   │
                                   ▼
                            EventBus.publish(next_event)
```

---

## 2. Event‑Driven Workflow Skeleton

### 2.1 Event Catalog (in lifecycle order)

| # | Event Name | Trigger | Emitted By | Consumed By |
|---|------------|---------|------------|-------------|
| 1 | `sprint.init` | CLI / API call with `project_id` and `requirement` | External (user) | `workflow-sprint-bootstrap` |
| 2 | `prd.completed` | PM finishes writing `prd.md` | `job-family-pm` | `workflow-architecture` |
| 3 | `solution.completed` | Architect finishes `solution.md` | `job-family-architect` | `workflow-delivery-plan` |
| 4 | `delivery_plan.completed` | Architect finishes `delivery_plan.json` | `job-family-architect` | `workflow-implementation` |
| 5 | `task_block.completed` | Engineer completes one task block | `job-family-engineer` | Self (loops until all blocks done) |
| 6 | `implementation.completed` | All task blocks complete | `job-family-engineer` | `workflow-review` |
| 7 | `review.completed` | PM + Architect finish review | `job-family-reviewer` | `workflow-acceptance` |
| 8 | `acceptance.completed` | Client approves / rejects | `job-family-client` | Terminal / Loop back |
| 9 | `sprint.completed` | Terminal event | `workflow-acceptance` | (none — terminal) |
| 10 | `sprint.rejected` | Client rejects | `workflow-acceptance` | `workflow-sprint-bootstrap` (re‑plan) |

### 2.2 Workflow Definitions (one per stage)

Each workflow is defined as a YAML file at `config/workflows/devsquad-<stage>.yaml` and registered in the workflow registry.

#### 2.2.1 `workflow-sprint-bootstrap`

```yaml
workflow_id: workflow-sprint-bootstrap
name: "DevSquad Sprint Bootstrap"
trigger_on: sprint.init
input_schema:
  type: object
  required: [project_id, requirement]
  properties:
    project_id: { type: string }
    requirement: { type: string }
    context: { type: string }
start_step: bootstrap_project
steps:
  - step_id: bootstrap_project
    step_type: tool_execute
    label: "Initialize project folder structure"
    config:
      tool: create_project_structure
      args:
        project_id: "{{ input.project_id }}"
    transitions:
      on_success: dispatch_pm
    retry_policy:
      max_retries: 2

  - step_id: dispatch_pm
    step_type: llm_call
    label: "Dispatch PM to write PRD"
    config:
      job_family: job-family-pm
      agent_id: agent-pm
      prompt_template: pm-prd-generation
      output_artifact: /projects/{{ input.project_id }}/prd.md
      context:
        requirement: "{{ input.requirement }}"
        project_id: "{{ input.project_id }}"
    transitions:
      on_success: publish_prd_completed
    retry_policy:
      max_retries: 1

  - step_id: publish_prd_completed
    step_type: tool_execute
    label: "Emit prd.completed event"
    config:
      tool: publish_event
      args:
        event_type: prd.completed
        payload:
          project_id: "{{ input.project_id }}"
          artifact_path: "/projects/{{ input.project_id }}/prd.md"
    transitions:
      on_success: completed
```

#### 2.2.2 `workflow-architecture`

```yaml
workflow_id: workflow-architecture
name: "DevSquad Architecture Phase"
trigger_on: prd.completed
input_schema:
  type: object
  required: [project_id, artifact_path]
  properties:
    project_id: { type: string }
    artifact_path: { type: string }
start_step: load_prd
steps:
  - step_id: load_prd
    step_type: tool_execute
    label: "Load PRD from artifact path"
    config:
      tool: read_file
      args:
        path: "{{ input.artifact_path }}"
    transitions:
      on_success: design_solution

  - step_id: design_solution
    step_type: llm_call
    label: "Architect designs solution"
    config:
      job_family: job-family-architect
      agent_id: agent-architect
      prompt_template: architect-solution-design
      output_artifact: /projects/{{ input.project_id }}/solution.md
      context:
        prd: "{{ steps.load_prd.result }}"
    transitions:
      on_success: publish_solution_completed

  - step_id: publish_solution_completed
    step_type: tool_execute
    label: "Emit solution.completed event"
    config:
      tool: publish_event
      args:
        event_type: solution.completed
        payload:
          project_id: "{{ input.project_id }}"
          artifact_path: "/projects/{{ input.project_id }}/solution.md"
    transitions:
      on_success: completed
```

#### 2.2.3 `workflow-delivery-plan`

```yaml
workflow_id: workflow-delivery-plan
name: "DevSquad Delivery Planning"
trigger_on: solution.completed
input_schema:
  type: object
  required: [project_id, artifact_path]
  properties:
    project_id: { type: string }
    artifact_path: { type: string }
start_step: load_solution
steps:
  - step_id: load_solution
    step_type: tool_execute
    config:
      tool: read_file
      args:
        path: "{{ input.artifact_path }}"
    transitions:
      on_success: create_delivery_plan

  - step_id: create_delivery_plan
    step_type: llm_call
    config:
      job_family: job-family-architect
      agent_id: agent-architect
      prompt_template: architect-delivery-plan
      output_artifact: /projects/{{ input.project_id }}/delivery_plan.json
      context:
        solution: "{{ steps.load_solution.result }}"
        prd_path: "/projects/{{ input.project_id }}/prd.md"
    transitions:
      on_success: publish_delivery_plan_completed

  - step_id: publish_delivery_plan_completed
    step_type: tool_execute
    config:
      tool: publish_event
      args:
        event_type: delivery_plan.completed
        payload:
          project_id: "{{ input.project_id }}"
          artifact_path: "/projects/{{ input.project_id }}/delivery_plan.json"
    transitions:
      on_success: completed
```

#### 2.2.4 `workflow-implementation`

```yaml
workflow_id: workflow-implementation
name: "DevSquad Implementation Phase"
trigger_on: delivery_plan.completed
input_schema:
  type: object
  required: [project_id, artifact_path]
  properties:
    project_id: { type: string }
    artifact_path: { type: string }
start_step: load_delivery_plan
steps:
  - step_id: load_delivery_plan
    step_type: tool_execute
    config:
      tool: read_file
      args:
        path: "{{ input.artifact_path }}"
    transitions:
      on_success: process_next_block

  - step_id: process_next_block
    step_type: condition
    label: "Check if more task blocks remain"
    config:
      condition: "{{ context.remaining_blocks | length > 0 }}"
    transitions:
      on_true: implement_block
      on_false: publish_implementation_completed

  - step_id: implement_block
    step_type: llm_call
    label: "Engineer implements one task block"
    config:
      job_family: job-family-engineer
      agent_id: agent-engineer
      prompt_template: engineer-implement-block
      output_artifact: /projects/{{ input.project_id }}/src/
      context:
        task_block: "{{ context.current_block }}"
        solution: "/projects/{{ input.project_id }}/solution.md"
        all_blocks: "{{ context.remaining_blocks }}"
    transitions:
      on_success: publish_block_completed

  - step_id: publish_block_completed
    step_type: tool_execute
    config:
      tool: publish_event
      args:
        event_type: task_block.completed
        payload:
          project_id: "{{ input.project_id }}"
          block_id: "{{ context.current_block.id }}"
    transitions:
      on_success: process_next_block

  - step_id: publish_implementation_completed
    step_type: tool_execute
    config:
      tool: publish_event
      args:
        event_type: implementation.completed
        payload:
          project_id: "{{ input.project_id }}"
          artifact_path: "/projects/{{ input.project_id }}/implementation.md"
    transitions:
      on_success: completed
```

#### 2.2.5 `workflow-review`

```yaml
workflow_id: workflow-review
name: "DevSquad Review Phase"
trigger_on: implementation.completed
input_schema:
  type: object
  required: [project_id, artifact_path]
  properties:
    project_id: { type: string }
    artifact_path: { type: string }
start_step: parallel_review
steps:
  - step_id: parallel_review
    step_type: council_deliberate
    label: "PM + Architect review implementation together"
    config:
      council_id: council-devsquad-review
      member_agent_ids: [agent-pm, agent-architect]
      arbitrator_agent_id: agent-pm
      max_analysis_tokens: 2000
      max_counter_tokens: 1000
      require_consensus: false
      context:
        prd: "/projects/{{ input.project_id }}/prd.md"
        solution: "/projects/{{ input.project_id }}/solution.md"
        delivery_plan: "/projects/{{ input.project_id }}/delivery_plan.json"
        implementation: "/projects/{{ input.project_id }}/src/"
    transitions:
      on_success: write_review_artifact

  - step_id: write_review_artifact
    step_type: tool_execute
    config:
      tool: write_file
      args:
        path: "/projects/{{ input.project_id }}/review.md"
        content: "{{ steps.parallel_review.result }}"
    transitions:
      on_success: publish_review_completed

  - step_id: publish_review_completed
    step_type: tool_execute
    config:
      tool: publish_event
      args:
        event_type: review.completed
        payload:
          project_id: "{{ input.project_id }}"
          artifact_path: "/projects/{{ input.project_id }}/review.md"
    transitions:
      on_success: completed
```

#### 2.2.6 `workflow-acceptance`

```yaml
workflow_id: workflow-acceptance
name: "DevSquad HITL Acceptance"
trigger_on: review.completed
input_schema:
  type: object
  required: [project_id, artifact_path]
  properties:
    project_id: { type: string }
    artifact_path: { type: string }
start_step: present_for_acceptance
steps:
  - step_id: present_for_acceptance
    step_type: user_input
    label: "Present deliverables to Client for acceptance"
    config:
      prompt_template: client-acceptance-request
      context:
        prd: "/projects/{{ input.project_id }}/prd.md"
        review: "/projects/{{ input.project_id }}/review.md"
        implementation: "/projects/{{ input.project_id }}/src/"
      input_schema:
        type: object
        required: [decision]
        properties:
          decision: { type: string, enum: [approved, rejected, changes_requested] }
          feedback: { type: string }
    transitions:
      on_success: process_decision

  - step_id: process_decision
    step_type: condition
    config:
      condition: "{{ steps.present_for_acceptance.result.decision == 'approved' }}"
    transitions:
      on_true: publish_sprint_completed
      on_false: publish_sprint_rejected

  - step_id: publish_sprint_completed
    step_type: tool_execute
    config:
      tool: publish_event
      args:
        event_type: sprint.completed
        payload:
          project_id: "{{ input.project_id }}"
    transitions:
      on_success: completed

  - step_id: publish_sprint_rejected
    step_type: tool_execute
    config:
      tool: publish_event
      args:
        event_type: sprint.rejected
        payload:
          project_id: "{{ input.project_id }}"
          feedback: "{{ steps.present_for_acceptance.result.feedback }}"
    transitions:
      on_success: completed
```

### 2.3 Event Registration

Register all events in `config/events/devsquad-events.yaml`:

```yaml
events:
  - event_type: sprint.init
    description: "External trigger to start a new DevSquad sprint"
    schema:
      type: object
      required: [project_id, requirement]
      properties:
        project_id: { type: string }
        requirement: { type: string }
        context: { type: string }

  - event_type: prd.completed
    description: "PM has completed the PRD artifact"
    schema:
      type: object
      required: [project_id, artifact_path]
      properties:
        project_id: { type: string }
        artifact_path: { type: string }

  - event_type: solution.completed
    description: "Architect has completed the solution design"
    schema:
      type: object
      required: [project_id, artifact_path]

  - event_type: delivery_plan.completed
    description: "Architect has completed the delivery plan"
    schema:
      type: object
      required: [project_id, artifact_path]

  - event_type: task_block.completed
    description: "Engineer completed one task block"
    schema:
      type: object
      required: [project_id, block_id]
      properties:
        project_id: { type: string }
        block_id: { type: string }

  - event_type: implementation.completed
    description: "All task blocks are implemented"
    schema:
      type: object
      required: [project_id, artifact_path]

  - event_type: review.completed
    description: "PM and Architect have reviewed the implementation"
    schema:
      type: object
      required: [project_id, artifact_path]

  - event_type: acceptance.completed
    description: "Client has accepted or rejected"
    schema:
      type: object
      required: [project_id, decision]
      properties:
        project_id: { type: string }
        decision: { type: string, enum: [approved, rejected, changes_requested] }
        feedback: { type: string }

  - event_type: sprint.completed
    description: "Terminal event — sprint successfully delivered"

  - event_type: sprint.rejected
    description: "Sprint rejected by client — loops back for re-planning"
    schema:
      type: object
      required: [project_id, feedback]
      properties:
        project_id: { type: string }
        feedback: { type: string }
```

---

## 3. Job Family Specifications

Each job family maps to one agent role and one lifecycle stage. A job family defines the input schema the agent receives, the output schema it must produce, the artifact path it writes to, and the event it emits on completion.

### 3.1 `job-family-pm` — Product Manager

| Field | Value |
|-------|-------|
| **job_family_id** | `job-family-pm` |
| **agent_id** | `agent-pm` |
| **description** | Generates a PRD from a raw requirement string |
| **trigger_event** | `sprint.init` |
| **completion_event** | `prd.completed` |

**Input Schema (`JobRecord.payload`):**
```json
{
  "type": "object",
  "required": ["project_id", "requirement"],
  "properties": {
    "project_id": {
      "type": "string",
      "description": "Unique project identifier, e.g. 'proj-2025-001'"
    },
    "requirement": {
      "type": "string",
      "description": "Raw requirement text from the Client"
    },
    "context": {
      "type": "string",
      "description": "Optional additional context (company, tech stack, constraints)"
    }
  }
}
```

**Output Schema (`JobRecord.result`):**
```json
{
  "type": "object",
  "required": ["artifact_path", "prd_summary"],
  "properties": {
    "artifact_path": {
      "type": "string",
      "description": "Absolute path to the written PRD, e.g. /projects/proj-2025-001/prd.md"
    },
    "prd_summary": {
      "type": "string",
      "description": "One-paragraph summary of the PRD for downstream agents"
    }
  }
}
```

**Artifact Path:** `/projects/<project_id>/prd.md`

**Example Payload (input):**
```json
{
  "project_id": "proj-2025-001",
  "requirement": "Build a REST API for a task management system with user auth, task CRUD, and team assignment. Must support 10k concurrent users.",
  "context": "Tech stack: Python/FastAPI, PostgreSQL. Team size: 3 engineers. Timeline: 2 weeks."
}
```

**Example Result (output):**
```json
{
  "artifact_path": "/projects/proj-2025-001/prd.md",
  "prd_summary": "PRD for Task Management API: 12 user stories across 4 epics (Auth, Tasks, Teams, Performance). Target: FastAPI + PostgreSQL. MVP scope defined for 2-week sprint."
}
```

### 3.2 `job-family-architect` — Architect

| Field | Value |
|-------|-------|
| **job_family_id** | `job-family-architect` |
| **agent_id** | `agent-architect` |
| **description** | Designs solution architecture and creates delivery plan |
| **trigger_events** | `prd.completed` (for solution), `solution.completed` (for delivery plan) |
| **completion_events** | `solution.completed`, `delivery_plan.completed` |

**Input Schema (solution phase):**
```json
{
  "type": "object",
  "required": ["project_id", "prd_content"],
  "properties": {
    "project_id": { "type": "string" },
    "prd_content": { "type": "string", "description": "Full PRD markdown content" },
    "prd_path": { "type": "string" }
  }
}
```

**Input Schema (delivery plan phase):**
```json
{
  "type": "object",
  "required": ["project_id", "solution_content"],
  "properties": {
    "project_id": { "type": "string" },
    "solution_content": { "type": "string", "description": "Full solution.md content" },
    "prd_path": { "type": "string" }
  }
}
```

**Output Schema (both phases):**
```json
{
  "type": "object",
  "required": ["artifact_path", "summary"],
  "properties": {
    "artifact_path": { "type": "string" },
    "summary": { "type": "string" }
  }
}
```

**Artifact Paths:** `/projects/<project_id>/solution.md`, `/projects/<project_id>/delivery_plan.json`

**Example Delivery Plan Payload:**
```json
{
  "project_id": "proj-2025-001",
  "solution_content": "# Solution: Task Management API\n\n## Architecture\n- FastAPI monolith with modular route design\n- PostgreSQL with SQLAlchemy ORM\n- JWT auth with refresh tokens\n...",
  "prd_path": "/projects/proj-2025-001/prd.md"
}
```

### 3.3 `job-family-engineer` — Engineer

| Field | Value |
|-------|-------|
| **job_family_id** | `job-family-engineer` |
| **agent_id** | `agent-engineer` |
| **description** | Implements one task block at a time from the delivery plan |
| **trigger_event** | `delivery_plan.completed` (first block), `task_block.completed` (subsequent blocks) |
| **completion_event** | `task_block.completed` (per block), `implementation.completed` (all blocks) |

**Input Schema:**
```json
{
  "type": "object",
  "required": ["project_id", "task_block", "solution_path", "delivery_plan_path"],
  "properties": {
    "project_id": { "type": "string" },
    "task_block": {
      "type": "object",
      "required": ["id", "title", "description", "files_to_create", "files_to_modify", "acceptance_criteria"],
      "properties": {
        "id": { "type": "string" },
        "title": { "type": "string" },
        "description": { "type": "string" },
        "files_to_create": { "type": "array", "items": { "type": "string" } },
        "files_to_modify": { "type": "array", "items": { "type": "string" } },
        "acceptance_criteria": { "type": "array", "items": { "type": "string" } },
        "dependencies": { "type": "array", "items": { "type": "string" } },
        "estimated_effort": { "type": "string", "enum": ["S", "M", "L", "XL"] }
      }
    },
    "solution_path": { "type": "string" },
    "delivery_plan_path": { "type": "string" },
    "all_blocks": { "type": "array", "description": "Full list of remaining blocks for context" },
    "completed_blocks": { "type": "array", "description": "Already-completed block IDs" }
  }
}
```

**Output Schema:**
```json
{
  "type": "object",
  "required": ["block_id", "files_created", "files_modified", "test_results", "build_status"],
  "properties": {
    "block_id": { "type": "string" },
    "files_created": { "type": "array", "items": { "type": "string" } },
    "files_modified": { "type": "array", "items": { "type": "string" } },
    "test_results": {
      "type": "object",
      "properties": {
        "passed": { "type": "integer" },
        "failed": { "type": "integer" },
        "skipped": { "type": "integer" },
        "output": { "type": "string" }
      }
    },
    "build_status": { "type": "string", "enum": ["passing", "failing"] },
    "self_review_notes": { "type": "string" }
  }
}
```

**Artifact Path:** `/projects/<project_id>/src/` (files written by the Engineer)

### 3.4 `job-family-reviewer` — PM + Architect Review

| Field | Value |
|-------|-------|
| **job_family_id** | `job-family-reviewer` |
| **agent_ids** | `[agent-pm, agent-architect]` |
| **description** | Council-based review of implementation against PRD and solution |
| **trigger_event** | `implementation.completed` |
| **completion_event** | `review.completed` |

**Input Schema:**
```json
{
  "type": "object",
  "required": ["project_id", "prd_path", "solution_path", "delivery_plan_path", "implementation_path"],
  "properties": {
    "project_id": { "type": "string" },
    "prd_path": { "type": "string" },
    "solution_path": { "type": "string" },
    "delivery_plan_path": { "type": "string" },
    "implementation_path": { "type": "string" }
  }
}
```

**Output Schema (CouncilOutcome):**
```json
{
  "type": "object",
  "required": ["decision", "confidence", "analyses", "dissent_notes"],
  "properties": {
    "council_id": { "type": "string" },
    "decision": { "type": "string", "enum": ["approved", "changes_requested", "rejected"] },
    "member_analyses": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "agent_id": { "type": "string" },
          "analysis": { "type": "string" },
          "issues_found": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "member_counters": { "type": "array" },
    "confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
    "dissent_notes": { "type": "string" }
  }
}
```

**Artifact Path:** `/projects/<project_id>/review.md`

### 3.5 `job-family-client` — Client / HITL

| Field | Value |
|-------|-------|
| **job_family_id** | `job-family-client` |
| **agent_id** | `agent-client` |
| **description** | Presents deliverables for human acceptance; waits for human input |
| **trigger_event** | `review.completed` |
| **completion_events** | `sprint.completed` or `sprint.rejected` |

**Input Schema:**
```json
{
  "type": "object",
  "required": ["project_id", "prd_path", "review_path", "implementation_path"],
  "properties": {
    "project_id": { "type": "string" },
    "prd_path": { "type": "string" },
    "solution_path": { "type": "string" },
    "review_path": { "type": "string" },
    "implementation_path": { "type": "string" },
    "implementation_summary": { "type": "string" }
  }
}
```

**Output Schema:**
```json
{
  "type": "object",
  "required": ["decision"],
  "properties": {
    "decision": { "type": "string", "enum": ["approved", "rejected", "changes_requested"] },
    "feedback": { "type": "string" },
    "accepted_artifacts": { "type": "array", "items": { "type": "string" } }
  }
}
```

**Artifact Path:** `/projects/<project_id>/acceptance.md`

---

## 4. Artifact Schemas

### 4.1 `prd.md` — Product Requirements Document

```markdown
# PRD: <Project Title>

**Project ID:** <project-id>
**Version:** 1.0
**Author:** agent-pm
**Created:** <ISO 8601 timestamp>
**Status:** Draft

## Executive Summary
<1-paragraph overview of what this project delivers and why>

## Problem Statement
<1-2 paragraphs describing the problem being solved>

## User Personas
### Persona 1: <Name>
- **Role:** <role description>
- **Goals:** <what this persona wants to accomplish>
- **Pain Points:** <current frustrations>

### Persona 2: <Name>
...

## Epics & User Stories
### Epic 1: <Epic Name>
**Goal:** <epic goal>

| ID | User Story | Acceptance Criteria | Priority | Effort |
|----|-----------|---------------------|----------|--------|
| US-01 | As a <role>, I want <goal> so that <reason> | 1. Given... When... Then... | P0 | S |
| US-02 | ... | ... | P1 | M |

### Epic 2: <Epic Name>
...

## Functional Requirements
- **FR-01:** <requirement description>
- **FR-02:** ...

## Non-Functional Requirements
- **NFR-01 (Performance):** <requirement>
- **NFR-02 (Security):** <requirement>
- **NFR-03 (Scalability):** <requirement>
- **NFR-04 (Reliability):** <requirement>

## Out of Scope (MVP)
- <item 1>
- <item 2>

## Dependencies & Assumptions
- **Dependencies:** <external systems, APIs, teams>
- **Assumptions:** <what we assume to be true>

## Glossary
| Term | Definition |
|------|-----------|
| <term> | <definition> |
```

### 4.2 `solution.md` — Architecture Solution

```markdown
# Solution Architecture: <Project Title>

**Project ID:** <project-id>
**Author:** agent-architect
**Based on PRD:** /projects/<project-id>/prd.md
**Created:** <ISO 8601 timestamp>

## Architecture Overview
<ASCII diagram showing high-level component layout>

## Technology Choices
| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Backend Framework | FastAPI | ... |
| Database | PostgreSQL | ... |
| Auth | JWT + OAuth2 | ... |
| Cache | Redis | ... |

## Component Design
### Component: <Name>
- **Responsibility:** <what it does>
- **Interface:** <API contract, method signatures>
- **Dependencies:** <other components it relies on>
- **Data Model:** <key entities and relationships>

### Component: <Name>
...

## Data Flow
<ASCII diagram or description of how data moves through the system>

## API Design
### Endpoints
| Method | Path | Description | Auth Required | Request Body | Response |
|--------|------|-------------|---------------|-------------|----------|
| POST | /api/v1/auth/login | User login | No | { email, password } | { access_token, refresh_token } |
| GET | /api/v1/tasks | List tasks | Yes | — | { tasks: [...] } |
...

## Security Considerations
- <auth strategy>
- <data protection>
- <threat mitigations>

## Testing Strategy
- **Unit tests:** <coverage target, framework>
- **Integration tests:** <scope>
- **E2E tests:** <scope>

## Risks & Mitigations
| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| <risk> | High/Med/Low | High/Med/Low | <mitigation> |
```

### 4.3 `delivery_plan.json` — Structured Delivery Plan

```json
{
  "$schema": "https://vai-core/schemas/delivery_plan.json",
  "project_id": "proj-2025-001",
  "version": "1.0",
  "created": "2025-01-15T10:00:00Z",
  "author": "agent-architect",
  "total_estimated_effort": "40h",
  "task_blocks": [
    {
      "id": "block-01",
      "title": "Project scaffolding and database setup",
      "description": "Initialize FastAPI project structure, configure SQLAlchemy, create initial migration, set up Docker Compose for PostgreSQL.",
      "files_to_create": [
        "src/main.py",
        "src/database.py",
        "src/models/__init__.py",
        "src/models/base.py",
        "alembic.ini",
        "alembic/env.py",
        "docker-compose.yml"
      ],
      "files_to_modify": [],
      "acceptance_criteria": [
        "FastAPI app starts and responds to GET /health",
        "Database connection pool is configured",
        "Alembic can run migrations up and down",
        "docker-compose up starts PostgreSQL"
      ],
      "dependencies": [],
      "estimated_effort": "M",
      "estimated_hours": 4
    },
    {
      "id": "block-02",
      "title": "User model and authentication",
      "description": "Implement User model with password hashing (bcrypt), JWT token generation and validation, login/logout endpoints, and refresh token rotation.",
      "files_to_create": [
        "src/models/user.py",
        "src/auth/__init__.py",
        "src/auth/jwt.py",
        "src/auth/dependencies.py",
        "src/routers/auth.py",
        "tests/test_auth.py"
      ],
      "files_to_modify": [
        "src/main.py",
        "src/database.py"
      ],
      "acceptance_criteria": [
        "POST /api/v1/auth/register creates a user with hashed password",
        "POST /api/v1/auth/login returns valid JWT access + refresh tokens",
        "GET /api/v1/auth/me returns current user when authenticated",
        "POST /api/v1/auth/refresh returns new token pair",
        "Expired tokens are rejected with 401",
        "All auth tests pass"
      ],
      "dependencies": ["block-01"],
      "estimated_effort": "L",
      "estimated_hours": 8
    }
  ],
  "execution_order": ["block-01", "block-02"],
  "parallel_groups": [],
  "rollback_plan": {
    "description": "If implementation fails, revert to last known good state",
    "steps": [
      "Keep feature branches per block",
      "Squash-merge only after all blocks pass review"
    ]
  }
}
```

### 4.4 `implementation.md` — Implementation Summary

```markdown
# Implementation Report: <Project Title>

**Project ID:** <project-id>
**Engineer:** agent-engineer
**Started:** <ISO 8601 timestamp>
**Completed:** <ISO 8601 timestamp>

## Block Completion Summary

| Block ID | Title | Status | Files Created | Files Modified | Tests (P/F/S) | Build |
|----------|-------|--------|---------------|----------------|---------------|-------|
| block-01 | Project scaffolding | ✅ Complete | 7 | 0 | 3/0/0 | ✅ |
| block-02 | User model and auth | ✅ Complete | 5 | 2 | 12/0/0 | ✅ |

## Files Changed
### Created
- `src/main.py`
- `src/database.py`
- ...

### Modified
- (none for initial sprint)

## Test Results
- **Total:** 15 passed, 0 failed, 0 skipped
- **Coverage:** 87%

## Self-Review Notes
<Engineer's own assessment of code quality, known issues, tech debt>

## Build Status: ✅ Passing
```

### 4.5 `review.md` — Review Artifact

```markdown
# Review Report: <Project Title>

**Project ID:** <project-id>
**Reviewers:** agent-pm, agent-architect
**Reviewed:** <ISO 8601 timestamp>

## Council Decision: <approved | changes_requested | rejected>
**Confidence:** <0.0 - 1.0>

## PM Analysis (agent-pm)
### Requirements Coverage
| User Story | Implemented? | Notes |
|------------|-------------|-------|
| US-01 | ✅ | ... |
| US-02 | ✅ | ... |

### Issues Found
- <issue or "None">

### Recommendation
<PM's overall assessment>

## Architect Analysis (agent-architect)
### Design Adherence
| Design Decision | Followed? | Notes |
|----------------|----------|-------|
| ... | ✅ | ... |

### Code Quality Issues
- <issue or "None">

### Recommendation
<Architect's overall assessment>

## Counter-Analysis (if dissent)
<Any disagreements between reviewers>

## Arbitration
<Final decision and rationale>

## Action Items
- [ ] <action item 1>
- [ ] <action item 2>
```

### 4.6 `acceptance.md` — Client Acceptance

```markdown
# Acceptance Report: <Project Title>

**Project ID:** <project-id>
**Client:** <client identifier>
**Reviewed:** <ISO 8601 timestamp>

## Decision: <Approved | Rejected | Changes Requested>

## Feedback
<Client's free-form feedback>

## Accepted Artifacts
- [ ] PRD (`prd.md`)
- [ ] Solution (`solution.md`)
- [ ] Delivery Plan (`delivery_plan.json`)
- [ ] Implementation (`src/`)
- [ ] Review (`review.md`)

## Sign-off
**Client:** _________________  **Date:** _________________
```

---

## 5. Project Folder Structure

Every DevSquad sprint lives under `/projects/<project-id>/`. The folder is created by the `create_project_structure` tool during the bootstrap workflow.

```
/projects/<project-id>/
├── prd.md                    # PM output — Product Requirements Document
├── solution.md               # Architect output — Architecture solution design
├── delivery_plan.json        # Architect output — Task blocks and execution order
├── implementation.md         # Engineer output — Implementation summary & test results
├── review.md                 # PM + Architect output — Council review report
├── acceptance.md             # Client output — Acceptance decision & feedback
├── feedback.json             # Client structured feedback (if changes requested)
├── metadata.json             # Sprint metadata (timestamps, status, versions)
│
├── src/                      # Engineer working directory — implementation files
│   ├── main.py
│   ├── database.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── user.py
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── jwt.py
│   │   └── dependencies.py
│   └── routers/
│       ├── __init__.py
│       └── auth.py
│
├── tests/                    # Engineer-written tests
│   ├── __init__.py
│   ├── conftest.py
│   └── test_auth.py
│
├── migrations/               # Database migrations (if applicable)
│   └── ...
│
└── artifacts/                # Versioned snapshots of each artifact
    ├── v1/
    │   ├── prd.md
    │   ├── solution.md
    │   └── delivery_plan.json
    └── v2/
        └── ...
```

### 5.1 `metadata.json` Schema

```json
{
  "project_id": "proj-2025-001",
  "title": "Task Management API",
  "status": "in_progress",
  "current_stage": "implementation",
  "stages": {
    "prd": { "status": "completed", "started": "...", "completed": "..." },
    "solution": { "status": "completed", "started": "...", "completed": "..." },
    "delivery_plan": { "status": "completed", "started": "...", "completed": "..." },
    "implementation": { "status": "in_progress", "started": "...", "completed": null },
    "review": { "status": "pending", "started": null, "completed": null },
    "acceptance": { "status": "pending", "started": null, "completed": null }
  },
  "created_at": "2025-01-15T09:00:00Z",
  "updated_at": "2025-01-15T14:30:00Z",
  "version": 1
}
```


---

## 6. Agent Prompt Templates

Each agent prompt template is stored as a YAML file at `config/prompts/devsquad-<role>-<task>.yaml` and loaded by the workflow engine when the `prompt_template` field is referenced in a step config.

### 6.1 PM — PRD Generation (`pm-prd-generation`)

**File:** `config/prompts/devsquad-pm-prd.yaml`

```yaml
prompt_id: pm-prd-generation
agent_id: agent-pm
description: "Generate a PRD from a raw requirement"
system_prompt: |
  You are {agent.persona}

  You are the Product Manager for a DevSquad sprint. Your sole responsibility is
  to transform raw client requirements into a thorough, unambiguous PRD.

  Follow this structure exactly:
  1. Executive Summary
  2. Problem Statement
  3. User Personas (at least 2)
  4. Epics & User Stories (with acceptance criteria in Given/When/Then format)
  5. Functional Requirements
  6. Non-Functional Requirements (Performance, Security, Scalability, Reliability)
  7. Out of Scope (MVP)
  8. Dependencies & Assumptions
  9. Glossary

  Rules:
  - Every user story MUST have at least one acceptance criterion
  - Prioritize stories as P0 (must-have), P1 (should-have), P2 (nice-to-have)
  - Estimate effort as S (<4h), M (4-8h), L (8-16h), XL (>16h)
  - The PRD must be self-contained; a downstream Architect must understand it
    without reading the original requirement
  - Write in clear, imperative language
  - Output VALID markdown — no malformed tables, no broken links

user_prompt: |
  Project ID: {project_id}
  Requirement: {requirement}
  Context: {context}

  Write the complete PRD as a single markdown document.
  Save it to: /projects/{project_id}/prd.md
```

### 6.2 Architect — Solution Design (`architect-solution-design`)

**File:** `config/prompts/devsquad-architect-solution.yaml`

```yaml
prompt_id: architect-solution-design
agent_id: agent-architect
description: "Design the architecture solution from a PRD"
system_prompt: |
  You are {agent.persona}

  You are the Architect for a DevSquad sprint. Your task is to read the PRD
  and produce a complete solution architecture document.

  Follow this structure exactly:
  1. Architecture Overview (include an ASCII diagram)
  2. Technology Choices (with rationale)
  3. Component Design (responsibility, interface, dependencies, data model)
  4. Data Flow
  5. API Design (full endpoint table)
  6. Security Considerations
  7. Testing Strategy
  8. Risks & Mitigations

  Rules:
  - Every PRD functional requirement must map to at least one component
  - API endpoints must include: method, path, auth required, request body, response
  - Data models must include field names, types, and constraints
  - Technology choices must have a "Rationale" column explaining WHY
  - The solution must be implementable by a single Engineer in the sprint timeframe
  - Output VALID markdown — no malformed tables, no broken links

user_prompt: |
  Project ID: {project_id}
  PRD: {prd}

  Design the complete solution architecture.
  Save it to: /projects/{project_id}/solution.md
```

### 6.3 Architect — Delivery Plan (`architect-delivery-plan`)

**File:** `config/prompts/devsquad-architect-delivery-plan.yaml`

```yaml
prompt_id: architect-delivery-plan
agent_id: agent-architect
description: "Break the solution into ordered task blocks"
system_prompt: |
  You are {agent.persona}

  You are the Architect for a DevSquad sprint. Your task is to read the solution
  design and break it into an ordered sequence of task blocks for the Engineer.

  Each task block must include:
  - `id`: Unique block identifier (e.g., "block-01")
  - `title`: Short descriptive title
  - `description`: What to implement and how
  - `files_to_create`: Array of exact file paths to create
  - `files_to_modify`: Array of exact file paths to modify
  - `acceptance_criteria`: Array of verifiable criteria
  - `dependencies`: Array of block IDs that must complete before this one
  - `estimated_effort`: S | M | L | XL
  - `estimated_hours`: Integer hours

  Rules:
  - Blocks must be ordered by dependency (no block references a later block)
  - Each block should be completable in < 8 hours
  - Include "Project scaffolding" as the first block (block-01)
  - Include "Integration tests and cleanup" as the last block
  - Every file in the solution design must appear in exactly one block
  - The Engineer must be able to execute blocks sequentially without ambiguity
  - Output VALID JSON — no trailing commas, no comments

user_prompt: |
  Project ID: {project_id}
  Solution: {solution}
  PRD path: {prd_path}

  Create the delivery plan as a JSON document.
  Save it to: /projects/{project_id}/delivery_plan.json
```

### 6.4 Engineer — Implement Block (`engineer-implement-block`)

**File:** `config/prompts/devsquad-engineer-implement.yaml`

```yaml
prompt_id: engineer-implement-block
agent_id: agent-engineer
description: "Implement one task block from the delivery plan"
system_prompt: |
  You are {agent.persona}

  You are the Engineer for a DevSquad sprint. Your task is to implement ONE
  task block from the delivery plan.

  You will receive:
  - The current task block specification
  - The full solution architecture (for context)
  - The list of all remaining blocks (for awareness)
  - The list of completed blocks (for awareness)

  You MUST:
  1. Create EVERY file listed in `files_to_create` with complete, working code
  2. Modify EVERY file listed in `files_to_modify` with the required changes
  3. Write unit tests for all new code
  4. Run the test suite and verify all tests pass
  5. Verify the build compiles / lints without errors
  6. Produce a self-review note listing any tech debt or concerns

  Rules:
  - Write production-quality code — not stubs, not TODOs, not placeholders
  - Follow the patterns and conventions established in the solution architecture
  - Every function must have a docstring
  - Every endpoint must have input validation
  - Do NOT modify files outside the block specification
  - After completing, report: files_created, files_modified, test_results, build_status

user_prompt: |
  Project ID: {project_id}

  ## Current Task Block
  {task_block}

  ## Solution Architecture
  (see: {solution_path})

  ## Completed Blocks
  {completed_blocks}

  ## Remaining Blocks
  {all_blocks}

  Implement this block now. Write all files to /projects/{project_id}/src/
  and /projects/{project_id}/tests/.
```

### 6.5 PM + Architect — Review (`reviewer-council`)

**File:** `config/prompts/devsquad-reviewer-council.yaml`

```yaml
prompt_id: reviewer-council
agent_ids: [agent-pm, agent-architect]
description: "Council review of implementation against PRD and solution"
system_prompt: |
  You are participating in a council review of a DevSquad sprint implementation.

  Council Members:
  - agent-pm (PM): Reviews against PRD requirements and user stories
  - agent-architect (Architect): Reviews against solution design and code quality
  - agent-pm (Arbitrator): Makes final decision if PM and Architect disagree

  Review Process:
  1. Each member analyzes the implementation independently
  2. Members present counter-analyses to each other's findings
  3. The arbitrator resolves disagreements and issues a final decision

  Decision Options:
  - `approved`: Implementation meets all requirements, no changes needed
  - `changes_requested`: Minor issues found, specific changes required
  - `rejected`: Major issues found, implementation must be redone

user_prompt: |
  Project ID: {project_id}

  Review the implementation against:
  - PRD: {prd_path}
  - Solution: {solution_path}
  - Delivery Plan: {delivery_plan_path}
  - Implementation: {implementation_path}

  Produce a review report. Save to: /projects/{project_id}/review.md
```

### 6.6 Client — Acceptance (`client-acceptance-request`)

**File:** `config/prompts/devsquad-client-acceptance.yaml`

```yaml
prompt_id: client-acceptance-request
agent_id: agent-client
description: "Present sprint deliverables to the Client for acceptance"
system_prompt: |
  You are {agent.persona}

  You are the Client representative for a DevSquad sprint. Your role is to
  review the completed deliverables and decide whether to accept them.

  You will be shown:
  - The original PRD (what was requested)
  - The review report (what PM and Architect found)
  - The implementation summary (what was built)

  You must decide:
  - `approved`: Deliverables meet your requirements — accept the sprint
  - `rejected`: Deliverables do NOT meet your requirements — reject with feedback
  - `changes_requested`: Mostly good but specific changes needed — provide details

  Be critical but fair. Base your decision on whether the implementation
  fulfills the PRD's user stories and acceptance criteria.

user_prompt: |
  Project ID: {project_id}

  ## Original PRD
  {prd}

  ## Review Report
  {review}

  ## Implementation Summary
  {implementation_summary}

  ## Implementation Files
  (see: {implementation_path})

  What is your decision? Provide specific feedback.
```


---

## 7. Execution Flow Example

This section provides a concrete, end-to-end example of a DevSquad sprint for a "Task Management API" project.

### 7.1 Project Initialization

**Trigger:** Client runs `vai devsquad start --project-id proj-2025-001 --requirement "Build a REST API for task management with user auth, task CRUD, and team assignment. 10k concurrent users."`

**Event emitted:** `sprint.init`

```json
{
  "event_type": "sprint.init",
  "payload": {
    "project_id": "proj-2025-001",
    "requirement": "Build a REST API for a task management system with user auth, task CRUD, and team assignment. Must support 10k concurrent users.",
    "context": "Tech stack: Python/FastAPI, PostgreSQL. Team size: 3 engineers. Timeline: 2 weeks."
  },
  "correlation_id": "corr-2025-001-001",
  "timestamp": "2025-01-15T09:00:00Z"
}
```

**Result:** Folder `/projects/proj-2025-001/` is created with empty `src/`, `tests/`, `migrations/`, `artifacts/` directories and `metadata.json` initialized.

### 7.2 Stage 1 — PRD Generation (PM)

**Workflow:** `workflow-sprint-bootstrap` step `dispatch_pm`

**Agent:** `agent-pm` with prompt template `pm-prd-generation`

**Sample PRD output** (excerpt from `/projects/proj-2025-001/prd.md`):

```markdown
# PRD: Task Management API

**Project ID:** proj-2025-001
**Version:** 1.0
**Author:** agent-pm
**Created:** 2025-01-15T09:30:00Z
**Status:** Draft

## Executive Summary
The Task Management API provides a RESTful backend for a collaborative task
management system. Users can authenticate, create and manage tasks, assign
tasks to team members, and track task status. The system targets 10k concurrent
users with sub-200ms p95 response times.

## Problem Statement
Current task tracking relies on spreadsheets and email, causing version
conflicts, lack of audit trails, and inability to enforce workflows. Teams
need a centralized API that supports structured task management with role-based
access control.

## User Personas
### Persona 1: Team Member
- **Role:** Individual contributor managing their own tasks
- **Goals:** Create, view, update, and complete assigned tasks
- **Pain Points:** Can't see team workload, no centralized task status

### Persona 2: Team Lead
- **Role:** Manager overseeing team tasks and assignments
- **Goals:** Assign tasks, monitor progress, generate reports
- **Pain Points:** No visibility into individual workloads, manual reassignment

## Epics & User Stories
### Epic 1: Authentication & Authorization
**Goal:** Secure user registration, login, and role-based access

| ID | User Story | Acceptance Criteria | Priority | Effort |
|----|-----------|---------------------|----------|--------|
| US-01 | As a user, I want to register an account so that I can access the system | Given valid email and password, When I POST /auth/register, Then I receive a confirmation and can log in | P0 | M |
| US-02 | As a user, I want to log in so that I can access protected resources | Given valid credentials, When I POST /auth/login, Then I receive a JWT access token and refresh token | P0 | M |

### Epic 2: Task CRUD
**Goal:** Full create, read, update, delete operations on tasks

| ID | User Story | Acceptance Criteria | Priority | Effort |
|----|-----------|---------------------|----------|--------|
| US-03 | As a user, I want to create tasks so that I can track work items | Given authenticated user, When I POST /tasks with title and description, Then task is created with status "open" | P0 | S |
| US-04 | As a user, I want to list my tasks so that I can see my workload | Given authenticated user, When I GET /tasks, Then I receive paginated tasks filtered by my assignments | P0 | M |
...
```

**Event emitted:** `prd.completed`

### 7.3 Stage 2 — Solution Design (Architect)

**Workflow:** `workflow-architecture`

**Sample solution.md output** (excerpt):

```markdown
# Solution Architecture: Task Management API

**Project ID:** proj-2025-001
**Author:** agent-architect
**Created:** 2025-01-15T10:15:00Z

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                   Client (Web/Mobile)             │
└─────────────────────┬───────────────────────────┘
                      │ HTTPS
┌─────────────────────▼───────────────────────────┐
│                 FastAPI Application               │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ Auth     │  │ Tasks    │  │ Teams         │  │
│  │ Router   │  │ Router   │  │ Router        │  │
│  └────┬─────┘  └────┬─────┘  └───────┬───────┘  │
│       │             │               │           │
│  ┌────▼─────────────▼───────────────▼───────┐   │
│  │              Service Layer                │   │
│  └────────────────────┬─────────────────────┘   │
│                       │                         │
│  ┌────────────────────▼─────────────────────┐   │
│  │           SQLAlchemy ORM                  │   │
│  └────────────────────┬─────────────────────┘   │
└───────────────────────┼─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│              PostgreSQL Database                  │
│  ┌─────────┐  ┌─────────┐  ┌─────────────────┐  │
│  │ users   │  │ tasks   │  │ teams           │  │
│  └─────────┘  └─────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────┘
```

## Technology Choices
| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Backend Framework | FastAPI 0.109+ | Native async, auto OpenAPI docs, Pydantic validation |
| Database | PostgreSQL 16 | ACID compliance, JSONB for flexible task metadata |
| ORM | SQLAlchemy 2.0 | Mature async support, Alembic migrations |
| Auth | JWT (python-jose) + bcrypt | Stateless auth, industry-standard password hashing |
| Cache | Redis 7 | Session storage, rate limiting, task queue |
...
```

**Event emitted:** `solution.completed`

### 7.4 Stage 3 — Delivery Plan (Architect)

**Sample delivery_plan.json output:**

```json
{
  "project_id": "proj-2025-001",
  "version": "1.0",
  "created": "2025-01-15T11:00:00Z",
  "author": "agent-architect",
  "total_estimated_effort": "36h",
  "task_blocks": [
    {
      "id": "block-01",
      "title": "Project scaffolding and database setup",
      "description": "Initialize FastAPI project structure, configure SQLAlchemy async engine, create User and Task models, run initial Alembic migration, set up Docker Compose for PostgreSQL + Redis.",
      "files_to_create": [
        "src/main.py", "src/database.py", "src/config.py",
        "src/models/__init__.py", "src/models/base.py",
        "src/models/user.py", "src/models/task.py",
        "alembic.ini", "alembic/env.py",
        "alembic/versions/001_initial.py",
        "docker-compose.yml", "Dockerfile"
      ],
      "files_to_modify": [],
      "acceptance_criteria": [
        "FastAPI app starts and GET /health returns 200",
        "Async PostgreSQL connection pool configured with 20 connections",
        "User and Task models defined with all fields from solution",
        "Alembic migration creates tables successfully",
        "docker-compose up starts PostgreSQL 16 and Redis 7"
      ],
      "dependencies": [],
      "estimated_effort": "M",
      "estimated_hours": 4
    },
    {
      "id": "block-02",
      "title": "Authentication module",
      "description": "Implement User registration and login. Use bcrypt for password hashing, python-jose for JWT generation/validation. Add refresh token rotation with Redis blocklist.",
      "files_to_create": [
        "src/auth/__init__.py", "src/auth/jwt.py",
        "src/auth/dependencies.py", "src/auth/schemas.py",
        "src/routers/auth.py",
        "tests/test_auth.py", "tests/conftest.py"
      ],
      "files_to_modify": ["src/main.py"],
      "acceptance_criteria": [
        "POST /api/v1/auth/register creates user with hashed password",
        "POST /api/v1/auth/login returns access_token + refresh_token",
        "GET /api/v1/auth/me returns current user from JWT",
        "POST /api/v1/auth/refresh rotates tokens, old refresh is blocklisted",
        "Expired/invalid tokens return 401",
        "12/12 unit tests pass"
      ],
      "dependencies": ["block-01"],
      "estimated_effort": "L",
      "estimated_hours": 8
    },
    {
      "id": "block-03",
      "title": "Task CRUD operations",
      "description": "Implement full CRUD for tasks with ownership, pagination, filtering, and sorting. Add TaskService layer between router and ORM.",
      "files_to_create": [
        "src/services/__init__.py", "src/services/task_service.py",
        "src/routers/tasks.py", "src/schemas/task.py",
        "tests/test_tasks.py"
      ],
      "files_to_modify": ["src/main.py"],
      "acceptance_criteria": [
        "POST /api/v1/tasks creates task with current user as owner",
        "GET /api/v1/tasks returns paginated tasks (default 20/page)",
        "GET /api/v1/tasks?status=open filters by status",
        "GET /api/v1/tasks?sort=created_at&order=desc sorts correctly",
        "PUT /api/v1/tasks/{id} updates task fields",
        "DELETE /api/v1/tasks/{id} soft-deletes task",
        "403 when accessing another user's task",
        "14/14 unit tests pass"
      ],
      "dependencies": ["block-02"],
      "estimated_effort": "L",
      "estimated_hours": 8
    }
  ]
}
```

**Event emitted:** `delivery_plan.completed`

### 7.5 Stage 4 — Implementation (Engineer, 3 blocks)

**Block 1 implementation output:**
```json
{
  "block_id": "block-01",
  "files_created": ["src/main.py", "src/database.py", "src/config.py", "..."],
  "files_modified": [],
  "test_results": { "passed": 3, "failed": 0, "skipped": 0 },
  "build_status": "passing",
  "self_review_notes": "Scaffolding is clean. Used asyncpg driver for PostgreSQL. Config loaded from environment variables with pydantic-settings."
}
```
**Event:** `task_block.completed` (block-01)

**Block 2 implementation output:**
```json
{
  "block_id": "block-02",
  "files_created": ["src/auth/__init__.py", "src/auth/jwt.py", "..."],
  "files_modified": ["src/main.py"],
  "test_results": { "passed": 12, "failed": 0, "skipped": 0 },
  "build_status": "passing",
  "self_review_notes": "JWT implementation follows best practices. Refresh token rotation with Redis blocklist works. One concern: access token expiry is hardcoded at 30min — should be configurable."
}
```
**Event:** `task_block.completed` (block-02)

**Block 3 implementation output:**
```json
{
  "block_id": "block-03",
  "files_created": ["src/services/task_service.py", "src/routers/tasks.py", "..."],
  "files_modified": ["src/main.py"],
  "test_results": { "passed": 14, "failed": 0, "skipped": 0 },
  "build_status": "passing",
  "self_review_notes": "Task CRUD is complete. Pagination uses fastapi-pagination. Soft delete uses a `deleted_at` timestamp. Filter logic could be refactored into a query builder if more filters are added later."
}
```
**Event:** `implementation.completed`

### 7.6 Stage 5 — Review (PM + Architect Council)

**Council deliberation result** (saved to `review.md`):

```markdown
# Review Report: Task Management API

**Project ID:** proj-2025-001
**Reviewers:** agent-pm, agent-architect
**Reviewed:** 2025-01-15T16:00:00Z

## Council Decision: approved
**Confidence:** 0.92

## PM Analysis (agent-pm)
### Requirements Coverage
| User Story | Implemented? | Notes |
|------------|-------------|-------|
| US-01 | ✅ | Registration endpoint functional with validation |
| US-02 | ✅ | JWT login with refresh token rotation |
| US-03 | ✅ | Task creation with ownership |
| US-04 | ✅ | Paginated task listing with filters |

### Issues Found
- None

### Recommendation
Implementation fully covers MVP scope. All acceptance criteria verified.

## Architect Analysis (agent-architect)
### Design Adherence
| Design Decision | Followed? | Notes |
|----------------|----------|-------|
| FastAPI async routes | ✅ | All routes use async def |
| SQLAlchemy 2.0 async | ✅ | AsyncSession with asyncpg |
| Service layer pattern | ✅ | TaskService abstracts ORM from router |
| JWT + bcrypt | ✅ | Industry-standard implementation |

### Code Quality Issues
- Minor: access_token_expiry should be configurable via env var (noted in self-review)

### Recommendation
Approve. The one code quality note is non-blocking and can be addressed next sprint.
```

**Event emitted:** `review.completed`

### 7.7 Stage 6 — HITL Acceptance (Client)

**Client decision:**
```json
{
  "decision": "approved",
  "feedback": "API meets all requirements. Auth flow is smooth, task CRUD covers all needed operations. Ready for frontend integration.",
  "accepted_artifacts": ["prd.md", "solution.md", "delivery_plan.json", "implementation.md", "review.md"]
}
```

**Event emitted:** `sprint.completed`

**Terminal state:** `/projects/proj-2025-001/metadata.json` updated with `status: "completed"`.

### 7.8 Rejection Path Example

If the Client had rejected:
```json
{
  "decision": "rejected",
  "feedback": "Missing team assignment feature (US-05). This was listed as P0 in the PRD but not implemented."
}
```
**Event emitted:** `sprint.rejected`

The `TriggerRouter` would map `sprint.rejected` back to `workflow-sprint-bootstrap`, restarting from PRD with the feedback incorporated.


---

## 8. Implementation Steps for DeepSeek‑Flash

This section provides a step-by-step guide for DeepSeek‑Flash to build the DevSquad pipeline from this roadmap. Follow these steps IN ORDER. Each step includes exactly what files to create and what values to use.

### Step 1: Create Agent Configurations

Create the four agent YAML configs:

**File: `config/agents/agent-pm.yaml`**
```yaml
agent_id: agent-pm
name: "DevSquad Product Manager"
description: "PM agent for DevSquad sprint pipeline. Transforms requirements into PRDs."
persona: |
  You are a seasoned Product Manager with 15 years of experience in enterprise
  software. You excel at translating vague client needs into precise, actionable
  product requirements. You are methodical, detail-oriented, and always think
  about the end user. You write clear, unambiguous user stories with testable
  acceptance criteria.
tools:
  - read_file
  - write_file
  - list_directory
workflows:
  - workflow-sprint-bootstrap
  - workflow-review
```

**File: `config/agents/agent-architect.yaml`**
```yaml
agent_id: agent-architect
name: "DevSquad Architect"
description: "Architect agent for DevSquad sprint pipeline. Designs solutions and creates delivery plans."
persona: |
  You are a Senior Solutions Architect with deep expertise in distributed systems,
  API design, and cloud-native architectures. You think in terms of components,
  interfaces, data flows, and trade-offs. You always choose the simplest solution
  that meets requirements. You document decisions with clear rationale.
tools:
  - read_file
  - write_file
  - list_directory
workflows:
  - workflow-architecture
  - workflow-delivery-plan
  - workflow-review
```

**File: `config/agents/agent-engineer.yaml`**
```yaml
agent_id: agent-engineer
name: "DevSquad Engineer"
description: "Engineer agent for DevSquad sprint pipeline. Implements task blocks from the delivery plan."
persona: |
  You are a Senior Full-Stack Engineer who writes clean, tested, production-ready
  code. You follow the solution architecture precisely. You never take shortcuts.
  Every function has a docstring. Every endpoint has validation. Every line of
  code is covered by tests. You think about edge cases, error handling, and
  performance from the start.
tools:
  - read_file
  - write_file
  - list_directory
  - execute_command
  - run_tests
workflows:
  - workflow-implementation
```

**File: `config/agents/agent-client.yaml`**
```yaml
agent_id: agent-client
name: "DevSquad Client"
description: "Client/HITL agent for DevSquad sprint pipeline. Reviews deliverables for acceptance."
persona: |
  You represent the client stakeholder. You review sprint deliverables against
  the original requirements. You are fair but critical. If something doesn't
  meet requirements, you say so clearly and provide actionable feedback.
tools:
  - read_file
  - list_directory
workflows:
  - workflow-acceptance
```

### Step 2: Create Event Definitions

**File: `config/events/devsquad-events.yaml`**

Use the exact YAML from [Section 2.3](#23-event-registration). Copy it verbatim.

### Step 3: Create Workflow Definitions

Create these six workflow YAML files using the exact YAML from [Section 2.2](#22-workflow-definitions-one-per-stage):

| File | Workflow ID | Trigger Event |
|------|-------------|---------------|
| `config/workflows/devsquad-bootstrap.yaml` | `workflow-sprint-bootstrap` | `sprint.init` |
| `config/workflows/devsquad-architecture.yaml` | `workflow-architecture` | `prd.completed` |
| `config/workflows/devsquad-delivery-plan.yaml` | `workflow-delivery-plan` | `solution.completed` |
| `config/workflows/devsquad-implementation.yaml` | `workflow-implementation` | `delivery_plan.completed` |
| `config/workflows/devsquad-review.yaml` | `workflow-review` | `implementation.completed` |
| `config/workflows/devsquad-acceptance.yaml` | `workflow-acceptance` | `review.completed` |

Each workflow YAML must include:
- `workflow_id`, `name`, `trigger_on`, `input_schema`, `start_step`, `steps`
- Every step must have `step_id`, `step_type`, `transitions` (on_success at minimum)
- LLM-call steps must include `config.job_family`, `config.agent_id`, `config.prompt_template`

### Step 4: Create Prompt Templates

Create these six prompt YAML files using the exact templates from [Section 6](#6-agent-prompt-templates):

| File | Prompt ID |
|------|-----------|
| `config/prompts/devsquad-pm-prd.yaml` | `pm-prd-generation` |
| `config/prompts/devsquad-architect-solution.yaml` | `architect-solution-design` |
| `config/prompts/devsquad-architect-delivery-plan.yaml` | `architect-delivery-plan` |
| `config/prompts/devsquad-engineer-implement.yaml` | `engineer-implement-block` |
| `config/prompts/devsquad-reviewer-council.yaml` | `reviewer-council` |
| `config/prompts/devsquad-client-acceptance.yaml` | `client-acceptance-request` |

### Step 5: Register Job Families

Create job family registrations in `config/job-families/devsquad.yaml`:

```yaml
job_families:
  - job_family_id: job-family-pm
    agent_id: agent-pm
    description: "Product Manager — generates PRDs"
    trigger_events: [sprint.init]
    completion_events: [prd.completed]
    max_retries: 1
    timeout_seconds: 1800

  - job_family_id: job-family-architect
    agent_id: agent-architect
    description: "Architect — designs solutions and delivery plans"
    trigger_events: [prd.completed, solution.completed]
    completion_events: [solution.completed, delivery_plan.completed]
    max_retries: 2
    timeout_seconds: 3600

  - job_family_id: job-family-engineer
    agent_id: agent-engineer
    description: "Engineer — implements task blocks"
    trigger_events: [delivery_plan.completed, task_block.completed]
    completion_events: [task_block.completed, implementation.completed]
    max_retries: 3
    timeout_seconds: 7200

  - job_family_id: job-family-reviewer
    agent_ids: [agent-pm, agent-architect]
    description: "Reviewer council — reviews implementation"
    trigger_events: [implementation.completed]
    completion_events: [review.completed]
    use_council: true
    council_id: council-devsquad-review
    max_retries: 1
    timeout_seconds: 1800

  - job_family_id: job-family-client
    agent_id: agent-client
    description: "Client/HITL — accepts or rejects deliverables"
    trigger_events: [review.completed]
    completion_events: [sprint.completed, sprint.rejected]
    requires_human_input: true
    max_retries: 0
    timeout_seconds: 86400
```

### Step 6: Create the Council Definition

**File:** `config/councils/devsquad-review.yaml` (the existing `config/councils/dev-squad.yaml` is for the full dev-squad panel; this one is specifically for the review stage):

```yaml
council_id: council-devsquad-review
name: "DevSquad Review Council"
description: "PM and Architect review implementation together"
arbitrator_agent_id: agent-pm
member_agent_ids:
  - agent-pm
  - agent-architect
max_analysis_tokens: 2000
max_counter_tokens: 1000
require_consensus: false
```

### Step 7: Create the Project Bootstrap Tool

Create a tool that initializes the project folder structure.

**File:** `src/tools/create_project_structure.py`

```python
"""Tool that creates the project folder structure for a DevSquad sprint."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_ROOT = Path("/projects")

DIRECTORIES = [
    "src",
    "tests",
    "migrations",
    "artifacts/v1",
]

METADATA_TEMPLATE = {
    "status": "initializing",
    "current_stage": "prd",
    "stages": {
        "prd": {"status": "pending", "started": None, "completed": None},
        "solution": {"status": "pending", "started": None, "completed": None},
        "delivery_plan": {"status": "pending", "started": None, "completed": None},
        "implementation": {"status": "pending", "started": None, "completed": None},
        "review": {"status": "pending", "started": None, "completed": None},
        "acceptance": {"status": "pending", "started": None, "completed": None},
    },
    "version": 1,
}


def execute(project_id: str, title: str = "") -> dict:
    """Create the project directory structure and metadata file."""
    project_dir = PROJECTS_ROOT / project_id

    if project_dir.exists():
        return {"status": "error", "error": f"Project {project_id} already exists"}

    # Create directories
    for dir_path in DIRECTORIES:
        (project_dir / dir_path).mkdir(parents=True, exist_ok=True)

    # Write metadata
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        **METADATA_TEMPLATE,
        "project_id": project_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
    }
    (project_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    return {
        "status": "success",
        "project_id": project_id,
        "project_dir": str(project_dir),
    }
```

### Step 8: Wire Up the TriggerRouter

Register all event-to-workflow mappings in the `TriggerRouter`.

**Add to:** `src/agent/workflow/trigger_router.py` (or wherever the router is configured):

```python
# DevSquad event-to-workflow mappings
DEVSQUAD_ROUTES = {
    "sprint.init": "workflow-sprint-bootstrap",
    "prd.completed": "workflow-architecture",
    "solution.completed": "workflow-delivery-plan",
    "delivery_plan.completed": "workflow-implementation",
    "task_block.completed": "workflow-implementation",
    "implementation.completed": "workflow-review",
    "review.completed": "workflow-acceptance",
    "sprint.rejected": "workflow-sprint-bootstrap",
}
```

### Step 9: Verification Checklist

After completing steps 1-8, verify the pipeline by executing this checklist:

| # | Check | Command / Method | Expected Result |
|---|-------|-----------------|-----------------|
| 1 | Agent configs load | `vai config validate agents` | All 4 agents pass validation |
| 2 | Event defs load | `vai config validate events` | All 10 events pass validation |
| 3 | Workflow defs load | `vai config validate workflows` | All 6 workflows pass validation |
| 4 | Prompt templates load | `vai config validate prompts` | All 6 prompts pass validation |
| 5 | Job families load | `vai config validate job-families` | All 5 job families pass validation |
| 6 | Bootstrap creates folders | `vai devsquad start --project-id test-001 --requirement "Test"` | `/projects/test-001/` created with all subdirectories |
| 7 | PRD is generated | (automatic after bootstrap) | `/projects/test-001/prd.md` exists, valid markdown |
| 8 | Architecture is generated | (automatic after PRD) | `/projects/test-001/solution.md` exists with ASCII diagram |
| 9 | Delivery plan is generated | (automatic after solution) | `/projects/test-001/delivery_plan.json` exists, valid JSON |
| 10 | Implementation runs | (automatic after delivery plan) | `/projects/test-001/src/` contains files, all tests pass |
| 11 | Review runs | (automatic after implementation) | `/projects/test-001/review.md` exists with council decision |
| 12 | Acceptance waits for input | (automatic after review) | System prompts for Client decision |

### Step 10: Edge Cases to Handle

DeepSeek‑Flash MUST handle these edge cases in the implementation:

| Edge Case | Handling |
|-----------|----------|
| **Project ID already exists** | Return error, do not overwrite |
| **PRD generation fails** | Retry once with same prompt; if still fails, emit `sprint.failed` event |
| **Solution misses a requirement** | Review stage catches this; loop back to solution if needed |
| **Engineer block fails tests** | Retry block up to 3 times; if still failing, emit failure with context |
| **Client times out (no response)** | After 24h timeout, auto-emit `sprint.rejected` with "timeout" reason |
| **Council deadlock (split decision)** | Arbitrator (agent-pm) breaks tie with final decision |
| **Concurrent sprints** | Each sprint runs in its own workflow instance, isolated by `project_id` |
| **Empty requirement** | Bootstrap step validates non-empty requirement before dispatching PM |

### Step 11: Directory Summary

After implementation, the following files should exist:

```
vai-core/
├── config/
│   ├── agents/
│   │   ├── agent-pm.yaml              # NEW
│   │   ├── agent-architect.yaml        # NEW
│   │   ├── agent-engineer.yaml         # NEW
│   │   └── agent-client.yaml           # NEW
│   ├── councils/
│   │   ├── dev-squad.yaml              # EXISTING (full panel)
│   │   └── devsquad-review.yaml        # NEW (review council)
│   ├── events/
│   │   └── devsquad-events.yaml        # NEW
│   ├── job-families/
│   │   └── devsquad.yaml              # NEW
│   ├── prompts/
│   │   ├── devsquad-pm-prd.yaml        # NEW
│   │   ├── devsquad-architect-solution.yaml   # NEW
│   │   ├── devsquad-architect-delivery-plan.yaml  # NEW
│   │   ├── devsquad-engineer-implement.yaml    # NEW
│   │   ├── devsquad-reviewer-council.yaml     # NEW
│   │   └── devsquad-client-acceptance.yaml    # NEW
│   └── workflows/
│       ├── devsquad-bootstrap.yaml     # NEW
│       ├── devsquad-architecture.yaml  # NEW
│       ├── devsquad-delivery-plan.yaml # NEW
│       ├── devsquad-implementation.yaml # NEW
│       ├── devsquad-review.yaml        # NEW
│       └── devsquad-acceptance.yaml    # NEW
├── src/
│   └── tools/
│       └── create_project_structure.py # NEW
└── docs/
    └── architecture/
        └── ROADMAP-devsquad.md         # THIS FILE
```

---

## Appendix A: Relationship to Existing Primitives

| Primitive | Used In DevSquad | How |
|-----------|-----------------|-----|
| **WorkflowEngine** | Every lifecycle stage | Each stage is a `WorkflowDefinition` executed by the engine |
| **EventBus** | Every stage transition | `publish_event` tool emits events; `TriggerRouter` subscribes |
| **JobQueue** | PM, Architect, Engineer dispatch | `InMemoryJobQueue.submit()` enqueues work; agents pull and execute |
| **CouncilOrchestrator** | Review stage | `council_deliberate` step type runs PM+Architect council |
| **Patterns** | Optional guidance | Patterns can be referenced in prompt templates via `apply_pattern` step type |
| **Project Isolation** | All artifacts | `/projects/<project-id>/` scopes all sprint data |

## Appendix B: Pattern Usage (Optional)

While the DevSquad pipeline does not REQUIRE patterns, the following patterns from `config/patterns/` MAY be used to enhance agent behavior:

- **`council-arbitration.yaml`**: Applied during review stage to structure the council deliberation
- **`subgoal-execute.yaml`**: Applied during implementation to break task blocks into sub-goals

To use a pattern, add an `apply_pattern` step before the LLM call step in the workflow definition:

```yaml
- step_id: apply_review_pattern
  step_type: apply_pattern
  config:
    pattern_id: council-arbitration
    inject_into_prompt: true
  transitions:
    on_success: parallel_review
```

---

**Document Version:** 1.0  
**Last Updated:** 2025-01-15  
**Next Steps:** DeepSeek‑Flash consumes this roadmap and executes Step 1 of Section 8.
