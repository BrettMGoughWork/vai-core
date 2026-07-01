"""LLM prompts used by the compaction pipeline."""

# ── Conversation summarisation (Phase 1.2) ─────────────────────────────

CONVERSATION_SUMMARY_SYSTEM = (
    "You are a conversation summarizer. Your task is to condense a long "
    "conversation history into a concise summary that preserves all "
    "information the AI assistant will need to continue working."
)

CONVERSATION_SUMMARY_USER = (
    "Summarize the following conversation history. Keep:\n"
    "- The user's overall goal\n"
    "- What has been accomplished so far\n"
    "- What is currently in progress\n"
    "- Any open questions or unresolved issues\n"
    "- Important decisions made and their rationale\n"
    "- Current blockers or errors encountered\n"
    "- Files that were created or modified\n"
    "- **Which tools were invoked** (by name) and why they were needed\n\n"
    "Discard:\n"
    "- Exact wording, greetings, and acknowledgments\n"
    "- Tool result details (the raw output from tool execution)\n"
    "- Repetitive or redundant statements\n\n"
    "IMPORTANT: The AI assistant has access to tool-calling capabilities\n"
    "(file read/write, search, command execution, etc.) and should continue\n"
    "to use them as needed. Make sure your summary conveys enough context\n"
    "that the assistant knows what tools are available and when to use them.\n\n"
    "Write a single coherent paragraph. Be concise but thorough.\n\n"
    "---\n{history}\n---"
)

# ── Structured state extraction (Phase 3) ────────────────────────────────

STATE_EXTRACTION_SYSTEM = (
    "You are a state-extraction engine. Analyze the provided conversation "
    "history and extract the current state as structured JSON. "
    "Return ONLY valid JSON with no explanatory text, no markdown fences, "
    "and no trailing punctuation."
)

STATE_EXTRACTION_USER = (
    "Analyze this conversation history and extract the current state. "
    "Return ONLY valid JSON with these fields:\n"
    "- goal: string — the user's overall goal\n"
    "- current_focus: string — what is being worked on right now\n"
    "- completed: string[] — list of completed items\n"
    "- blocked: string[] — items that can't proceed\n"
    "- next_steps: string[] — immediate next actions\n"
    "- important_decisions: string[] — decisions made and their rationale\n"
    "- open_questions: string[] — questions not yet answered\n"
    "- files_created: string[] — files that were created\n"
    "- files_modified: string[] — files that were modified\n"
    "- errors_encountered: string[] — errors or blockers encountered\n\n"
    "Be concise. Each array item should be a single sentence or less. "
    "If a field has nothing to report, use an empty array [] or empty string \"\".\n\n"
    "---\n{history}\n---"
)

# ── Subgoal completion summary (Phase 1.3) ─────────────────────────────

SUBGOAL_COMPLETION_SYSTEM = (
    "You are a task summarizer. A subgoal has been completed, and you "
    "need to produce a compact record of what happened."
)

SUBGOAL_COMPLETION_USER = (
    "The subgoal '{goal}' is complete. Summarize the relevant conversation "
    "history into a compact record covering:\n"
    "- What was accomplished\n"
    "- What files were created or modified\n"
    "- Any issues or blockers encountered\n"
    "- The final status\n\n"
    "Write 2-3 concise sentences.\n\n"
    "---\n{history}\n---"
)
