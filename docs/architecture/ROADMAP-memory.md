# Memory Compaction Pipeline — Implementation Plan

## Assessment of User's Notes

| Level | User's Name | Verdict | Rationale |
|---|---|---|---|
| 1 | Conversation Summarization | **INCLUDE** — Phase 1 MVP | Simple, high token reduction, no new infrastructure needed |
| 2 | State Extraction | **INCLUDE** — Phase 3 | Structured output is better than prose summary; builds on Phase 1 |
| 3 | Event Compaction | **INCLUDE** — Phase 2 | Huge win for coding agents; tool call dedup is straightforward |
| 4 | Subgoal Completion Compaction | **INCLUDE** — Phase 1 | Existing hooks at `memory_governance.py:96-100`, eviction orchestrator placeholder ready. Highest ROI. |
| 5 | Semantic Compression / Learnings | **DEFER** | Needs a "learned facts" store, retrieval, and a second LLM call per compaction. Too complex for v1. |
| Memory Hierarchy | **DEFER** | Needs a knowledge store with retrieval (embeddings or vector DB). Out of scope for now. |
| Episodic Memory | **DEFER** | Needs successful-trajectory storage + similarity retrieval. v2 material. |
| Architecture Retrieval | **DISCARD** | The "86k architecture JSON" (`docs/architecture.json`) is NOT injected into LLM context — it's a dev/CI artifact. Nothing to compress here. |

### Triggers to implement (vs defer)

| Trigger | Verdict | Why |
|---|---|---|
| Context pressure (>80% used) | **INCLUDE** — Phase 1 | Requires token counting (prerequisite). Primary trigger. |
| Subgoal completion | **INCLUDE** — Phase 1 | Hook exists. Automatic compaction on CLOSED transition. |
| Every N turns | **INCLUDE** — Phase 1 | Simple counter. Low-effort safety net. |
| Large tool output (>10k chars) | **INCLUDE** — Phase 2 | Detect in tool_orchestrator before appending to history. |
| Workflow completion | **DEFER** | Workflows are too varied for a generic hook. Subgoal completion covers the important case. |

---

## Phase 0: Token Counting Infrastructure (Prerequisite)

**Why first**: Context-pressure triggers, context-capacity tracking, and "is compaction needed?" decisions all require knowing how many tokens are in play. Currently zero token counting exists in the codebase.

### 0.1 Add token counting utility

Create new file: `src/runtime/llm/token_counter.py`

```python
"""
Token counting for context-window management.

Uses tiktoken with cl100k_base encoding (GPT-4 / GPT-4o / most modern models).
Supports pluggable encodings for non-OpenAI models.
"""

import tiktoken
from typing import List, Dict, Any, Optional

# Default encoding — covers GPT-4, GPT-4o, GPT-4-turbo, DeepSeek-V2+, etc.
DEFAULT_ENCODING = "cl100k_base"

# Known context-window limits by model (input + output).  Output budgets
# are subtracted to arrive at the "safe input" ceiling.
MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    "deepseek-chat": 65536,       # 64K context window
    "deepseek-reasoner": 65536,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "claude-3-5-sonnet-20241022": 200000,
    "claude-3-opus-20240229": 200000,
    "gemini-2.0-flash": 1048576,
    "gemini-1.5-pro": 2097152,
    "qwen-max": 32768,
    "mistral-large": 131000,
}


class TokenCounter:
    """Count tokens in messages, tool definitions, and conversation history."""

    def __init__(self, encoding_name: str = DEFAULT_ENCODING):
        self._encoding = tiktoken.get_encoding(encoding_name)

    def count_text(self, text: str) -> int:
        """Count tokens in a plain string."""
        return len(self._encoding.encode(text))

    def count_message(self, msg: Dict[str, Any]) -> int:
        """Count tokens in a single message dict (role + content + tool_calls)."""
        # OpenAI formula: 4 tokens per message + role + content
        tokens = 4  # message framing overhead
        for key in ("role", "content"):
            if key in msg and isinstance(msg[key], str):
                tokens += len(self._encoding.encode(msg[key]))
        # tool_calls contribute name + arguments tokens
        if "tool_calls" in msg and isinstance(msg["tool_calls"], list):
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                tokens += len(self._encoding.encode(func.get("name", "")))
                tokens += len(self._encoding.encode(func.get("arguments", "{}")))
                tokens += 4  # tool_call framing overhead
        if "tool_call_id" in msg:
            tokens += len(self._encoding.encode(str(msg["tool_call_id"])))
        return tokens

    def count_messages(self, messages: List[Dict[str, Any]]) -> int:
        """Count tokens across a list of messages."""
        return sum(self.count_message(m) for m in messages)

    def count_tool_definitions(self, tools: List[Dict[str, Any]]) -> int:
        """Count tokens consumed by tool/function definitions."""
        tokens = 0
        for tool in tools:
            func = tool.get("function", {})
            tokens += len(self._encoding.encode(func.get("name", "")))
            tokens += len(self._encoding.encode(func.get("description", "")))
            params = func.get("parameters", {})
            if params:
                import json
                tokens += len(self._encoding.encode(json.dumps(params, separators=(",", ":"))))
        return tokens


def get_context_limit(model: str, output_budget: int = 4096) -> Optional[int]:
    """Return safe input token ceiling for a model."""
    limit = MODEL_CONTEXT_LIMITS.get(model)
    if limit is None:
        return None
    return limit - output_budget


# Module-level convenience
_counter = TokenCounter()
count_tokens_in_text = _counter.count_text
count_tokens_in_messages = _counter.count_messages
count_tokens_in_tools = _counter.count_tool_definitions
```

### 0.2 Add `tiktoken` dependency

In `pyproject.toml` or `requirements.txt`, add: `tiktoken>=0.7.0`

### 0.3 Wire token counting into `client.py`

In `src/runtime/llm/client.py`, after line 375 (before LLM call), add token counting:

```python
# --- INSERT after line 358 (after _to_openai_tools call) ---
from src.runtime.llm.token_counter import (
    count_tokens_in_messages,
    count_tokens_in_tools,
    get_context_limit,
)

# Count tokens for context-pressure tracking
input_tokens = count_tokens_in_messages(messages) + count_tokens_in_tools(tools)
context_limit = get_context_limit(model, output_budget=max_tokens or 4096)
if context_limit:
    context_pressure = input_tokens / context_limit  # 0.0-1.0+  (can exceed 1.0)
else:
    context_pressure = 0.0

# Store in response metadata
# (add token_count and context_pressure fields to PromptResponse/RuntimeResponse)
```

### 0.4 Add token fields to response types

In `src/runtime/llm/response_types.py` (or wherever `PromptResponse`/`RuntimeResponse` is defined):

Add fields:
- `input_tokens: int = 0`
- `context_pressure: float = 0.0`

---

## Phase 1: Conversation Summarization (Level 1) + Subgoal Compaction (Level 4)

### 1.1 Create the CompactionOrchestrator

New file: `src/agent/memory/compaction/compaction_orchestrator.py`

This is the central coordinator. Responsibilities:
- Evaluate triggers (context pressure, turn count, subgoal completion)
- Decide WHAT to compact
- Call the LLM to produce summaries
- Replace old conversation history entries with summaries
- Store compacted subgoal traces

```python
"""
CompactionOrchestrator — decides when and what to compact in conversation history.

Evaluates multiple triggers:
  1. Context pressure > COMPACTION_THRESHOLD (default 0.8)
  2. Turn count exceeds TURN_THRESHOLD (default 10)
  3. Subgoal marked CLOSED (inbound signal from memory_governance)
  4. Individual tool result exceeds TOOL_OUTPUT_THRESHOLD (default 10_000 chars)

Integration points:
  - client.py:363 (before conversation_history loop) — evaluate & compact
  - memory_governance.py:100 — signal subgoal completion
  - tool_orchestrator.py:416 — detect large tool outputs
"""
```

**Configuration** (new section in `config/config.yaml` or a new `config/compaction.yaml`):
```yaml
compaction:
  enabled: true
  context_pressure_threshold: 0.8      # 0.0-1.0, trigger when input tokens > 80% of limit
  turn_count_threshold: 10             # compact every N user+assistant turn pairs
  tool_output_threshold: 10000         # chars, auto-summarize tool results above this
  keep_recent_turns: 4                 # always keep the last N turns un-compacted
  summary_style: "prose"               # "prose" = paragraph summary (Phase 1), "structured" = JSON (Phase 2)
```

### 1.2 Implement conversation summarization

**Integration point**: `src/runtime/llm/client.py`, lines 363-373.

**Logic flow**:
```
1. Before the `for entry in conversation_history` loop:
   a. Count total tokens in conversation_history
   b. Count total turns (user+assistant pairs)
   c. Check: context_pressure > threshold OR turn_count > threshold
   d. If trigger fires:
      - Split history: keep_last_N_turns (default 4) + older_turns
      - Call LLM: "Summarize this conversation history. Keep: the user's goal,
        what's been accomplished, what's in progress, any open questions,
        important decisions, and current blockers. Discard: exact wording,
        greeting/acknowledgment messages, and tool result details."
      - Replace older_turns with a single system-prefix summary message:
        {"role": "system", "content": "[CONVERSATION SUMMARY]\n" + summary}
      - The keep_last_N_turns remain unchanged as immediate context
   e. Continue with the normal loop (now iterating summary + recent turns)
```

**Key design decisions**:
- Summary is injected as `role: "system"` so the model treats it as context, not conversation
- Always keep the last N turns — the compaction must not destroy the immediate thread
- The compaction LLM call itself costs tokens, but the net reduction should be 5-10x for long conversations
- Use the existing LLM transport (via the same provider) — no need for a separate model

### 1.3 Implement subgoal completion compaction

**Hook already exists**: `memory_governance.py:96-100`

```python
# In memory_governance.py, after line 100:
if self._eviction_orchestrator is not None and existing is not None:
    prev_state = existing.state.lower()
    new_state = incoming.state.lower()
    if prev_state != "closed" and new_state == "closed":
        self._eviction_orchestrator.on_subgoal_completed(subgoal.subgoal_id)
        # NEW: also notify compaction orchestrator
        if self._compaction_orchestrator:
            self._compaction_orchestrator.on_subgoal_closed(
                subgoal_id=subgoal.subgoal_id,
                goal=subgoal.goal,
                context=subgoal.context,
            )
```

**What happens on subgoal completion**:
1. Find all conversation history entries related to that subgoal's execution window
2. Call LLM: "The subgoal '{goal}' is complete. Summarize the relevant conversation history entries into a compact record: what was accomplished, what files were created/modified, any issues encountered, and the final status."
3. Replace those history entries with a single system message:
   ```
   [SUBGOAL COMPLETE: {goal}]
   Accomplished: {summary}
   Files: {file_list}
   Status: completed
   ```
4. Store the full compacted record in subgoal memory for future retrieval

### 1.4 Wire into the pipeline

In `composition_root.py`, add to the `_build_s5_adapter` function:
```python
from src.agent.memory.compaction.compaction_orchestrator import CompactionOrchestrator

compaction_orchestrator = CompactionOrchestrator(
    llm_transport=llm_transport,   # reuse existing LLM transport
    config=config.get("compaction", {}),
)

# Pass to memory_governance
memory_governance.set_compaction_orchestrator(compaction_orchestrator)
```

In `client.py`, before line 363:
```python
# Compaction check (if orchestrator provided in request context)
compaction_orchestrator = request.memory.get("_compaction_orchestrator")
if compaction_orchestrator:
    conversation_history = compaction_orchestrator.compact_if_needed(
        conversation_history=conversation_history,
        model=model,
        max_tokens=max_tokens,
    )
```

---

## Phase 2: Event Compaction (Level 3) + Large Output Summarization

### 2.1 Tool call deduplication

**Integration point**: `tool_orchestrator.py`, lines 408-420 (where tool results are appended).

**Logic**:
Before appending a tool result message, check if:
1. The same file was previously edited in this conversation turn
2. The previous edit can be replaced with a combined "File X created and modified N times" entry
3. Tool outputs exceed the threshold and should be summarized, not stored raw

**Implementation**:

```python
# In tool_orchestrator.py, _run_follow_up_llm, around line 414-420:

# Before appending, check if this is a file-targeting tool call
file_target = pe.get("metadata", {}).get("target_file")
if file_target:
    # Find previous operations on same file in this turn
    prev_entry = _find_previous_file_entry(conversation_history, file_target)
    if prev_entry:
        # Replace with compacted version instead of adding new entry
        prev_entry["content"] = _compact_file_operations(
            file_target, prev_entry["content"], pe["result_str"]
        )
        continue  # skip appending a new entry

# Large output detection
result_str = pe["result_str"]
if len(result_str) > TOOL_OUTPUT_THRESHOLD:
    result_str = _summarize_large_output(result_str, pe["name"], llm_transport)

conversation_history.append({...})  # normal append
```

### 2.2 Large output summarization

For tool outputs >10k characters (e.g., test runs, log dumps, file reads):
- Extract the first 500 chars (for context) + last 500 chars (for results/conclusions)
- Call LLM to produce a 2-3 sentence summary
- Store: `[SUMMARIZED OUTPUT: {tool_name}]\n{summary}\n---first 500 chars---\n{first_chars}\n---last 500 chars---\n{last_chars}`

This preserves the signal (what happened, what was the result) while discarding the noise (10k lines of build output).

---

## Phase 3: State Extraction (Level 2)

### 3.1 Structured state summary

Instead of a prose summary (Phase 1), produce structured JSON:

```json
{
  "goal": "Build API for user management",
  "current_focus": "Database migration",
  "completed": ["User endpoints", "Auth middleware", "Unit tests"],
  "blocked": [],
  "next_steps": ["Fix migration", "Add integration tests"],
  "important_decisions": ["Chose JWT over session auth", "Use SQLite for dev"],
  "open_questions": ["Should we add rate limiting?"],
  "files_created": ["src/api/users.py", "src/auth/middleware.py"],
  "files_modified": ["src/db/migrations/003_add_users.sql"],
  "errors_encountered": ["Migration 003 conflicts with 002 — needs resolution"]
}
```

**Implementation**: Replace the prose LLM prompt in Phase 1 with a structured-extraction prompt:

```
Analyze this conversation history and extract the following structured state.
Return ONLY valid JSON with these fields:
- goal: string — the user's overall goal
- current_focus: string — what is being worked on right now
- completed: string[] — list of completed items
- blocked: string[] — items that can't proceed
- next_steps: string[] — immediate next actions
- important_decisions: string[] — decisions made and their rationale
- open_questions: string[] — questions not yet answered
- files_created: string[] — files that were created
- files_modified: string[] — files that were modified
- errors_encountered: string[] — errors or blockers encountered

Be concise. Each array item should be a single sentence or less.
If a field has nothing to report, use an empty array [] or empty string "".
```

### 3.2 State-aware context injection

When state exists from a previous compaction, inject it as a system message BEFORE the conversation summary:

```
[CURRENT STATE]
Goal: Build API for user management
Focus: Database migration
Completed: User endpoints, Auth middleware, Unit tests
Next: Fix migration, Add integration tests
Blocked: (none)
```

This gives the model a "dashboard" view before it reads conversation details.

---

## File Changes Summary

| File | Change | Phase |
|---|---|---|
| `pyproject.toml` / `requirements.txt` | Add `tiktoken>=0.7.0` | 0 |
| `src/runtime/llm/token_counter.py` | **NEW** — token counting utility | 0 |
| `src/runtime/llm/client.py` | Add compaction hook before line 363; add token counting after line 375; add token fields to response | 0, 1 |
| `src/runtime/llm/response_types.py` | Add `input_tokens`, `context_pressure` fields | 0 |
| `src/agent/memory/compaction/__init__.py` | **NEW** — package init | 1 |
| `src/agent/memory/compaction/compaction_orchestrator.py` | **NEW** — central orchestrator | 1 |
| `src/agent/memory/compaction/summary_prompts.py` | **NEW** — LLM prompts for summarization | 1 |
| `src/agent/memory/compaction/compaction_types.py` | **NEW** — data types (CompactionConfig, CompactionResult, CompactionTrigger) | 1 |
| `src/agent/memory/governance/memory_governance.py` | Add compaction orchestrator notification on subgoal CLOSED | 1 |
| `src/agent/memory/eviction/eviction_orchestrator.py` | Wire `on_episode_compacted` to compaction pipeline | 1 |
| `src/agent/composition_root.py` | Create and wire CompactionOrchestrator | 1 |
| `src/agent/tool_orchestrator.py` | Add tool dedup (lines 408-420); add large-output summarization (line 416) | 2 |
| `config/config.yaml` | Add `compaction:` section | 1 |

## Tests to write

| Test file | What it covers |
|---|---|
| `tests/unit/test_token_counter.py` | Token counting accuracy for messages, tools, text |
| `tests/unit/test_compaction_orchestrator.py` | Trigger evaluation: context pressure, turn count, subgoal signal |
| `tests/unit/test_compaction_summarization.py` | LLM prompt construction, history splitting logic |
| `tests/unit/test_tool_deduplication.py` | File-targeting dedup, large output detection |
| `tests/integration/test_compaction_pipeline.py` | End-to-end: long conversation → compaction → reduced tokens → correct LLM response |

---

## Implementation Order (for DeepSeek Flash)

This is ordered to ensure each phase builds on the previous one and delivers standalone value:

1. **Phase 0** — Token counting (no behavior change, just measurement)
2. **Phase 1** — Conversation summarization + subgoal compaction (the core pipeline)
3. **Phase 2** — Event compaction + large output summarization (optimization layer)
4. **Phase 3** — State extraction (quality improvement over prose summaries)

Each phase should be a separate PR to keep review manageable.

## Critical Design Constraints

1. **The compaction LLM call itself uses tokens** — always verify net reduction. If the summary would be larger than what it replaces, skip compaction.

2. **Never compact the last N turns** — `keep_recent_turns` (default 4) must remain untouched so the model has immediate conversational context.

3. **Subgoal compaction is irreversible** — once a subgoal's execution trace is replaced with a summary, the details are gone. The summary must be thorough enough that the agent can continue working without those details.

4. **Fingerprint-based staleness** — reuse the existing `SummaryMetadata` pattern from `summary_types.py`. If conversation history hasn't changed since last compaction, skip the LLM call.

5. **Graceful degradation** — if the compaction LLM call fails (timeout, rate limit), continue with uncompacted history. Compaction is an optimization, not a requirement.
