"""
DevSquad Sprint Interviewer
============================

Interactive CLI agent that collects a north-star description from the user
(either as free text or via a file dropped in the inbox), validates it with
an LLM, then publishes a ``sprint.init`` event to kick off the pipeline.

Usage::

    python -m src.devsquad.interview

Or programmatically::

    from src.devsquad import extract_sprint_params, kickoff_sprint

    params = extract_sprint_params("Build a CLI tool for..."[, llm_callable])
    kickoff_sprint(params)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Imports that bootstrap composition_root (loads .env, LLM, event bus, etc.)
# ---------------------------------------------------------------------------
from src.agent.composition_root import get_event_bus, _llm_complete  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECTS_ROOT = Path(os.environ.get("DEVSQUAD_PROJECTS_ROOT", ".\\projects"))
_INBOX_DIR = _PROJECTS_ROOT / "inbox"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BANNER = r"""
+------------------------------------------------------------+
|           DevSquad Sprint Interviewer v1.0                  |
+------------------------------------------------------------+
"""


def _ensure_inbox() -> Path:
    """Create the inbox directory if it doesn't exist. Return its path."""
    _INBOX_DIR.mkdir(parents=True, exist_ok=True)
    return _INBOX_DIR


def _print_section(label: str, body: str, indent: int = 2) -> None:
    pad = " " * indent
    print()
    print(f"{pad}-- {label} --")
    for line in body.strip().splitlines():
        print(f"{pad}{line}")
    print()


def _collect_user_input() -> str:
    """Greet the user and collect their north-star description.

    Accepts either free text (multi-line terminated by a blank line or ``/end``)
    or a file path to a markdown file in the inbox.
    """
    inbox = _ensure_inbox()

    print(_BANNER)
    print("I'll help you kick off a DevSquad sprint.\n")
    print("You can:")
    print(f"  1. Describe your project in free text (type your thoughts)")
    print(f"  2. Drop a .md file in {inbox} and give me the filename")
    print()
    print("What are we building today?")
    print("(Type your answer, or press Enter twice to finish multi-line input)")
    print()

    lines: list[str] = []
    blank_count = 0
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        stripped = line.strip()

        # Check if user provided a file path
        if not lines and stripped:
            # First non-blank line — could be a file path
            candidate = Path(stripped)
            if not candidate.is_absolute():
                candidate = _INBOX_DIR / stripped
            if candidate.suffix.lower() in (".md", ".markdown", ".txt") and candidate.exists():
                print(f"  (Reading file: {candidate})")
                content = candidate.read_text(encoding="utf-8")
                _print_section("File contents", content)
                try:
                    confirm = input("  Use this content as your north star? (Y/n): ").strip().lower()
                except EOFError:
                    confirm = "y"  # default to yes in non-interactive/pipe mode
                if confirm not in ("n", "no"):
                    return content
                print("  OK, let's try again. What are we building?")
                lines.clear()
                continue

        if stripped == "/end":
            break
        if not stripped:
            blank_count += 1
            if blank_count >= 2 and lines:
                break
            continue

        blank_count = 0
        lines.append(stripped)

    if not lines:
        print("No input provided. Exiting.")
        sys.exit(1)

    return "\n".join(lines)


# ── System prompt used by extract_sprint_params ──────────────────────

_EXTRACTION_SYSTEM_PROMPT = (
    "You are a friendly, experienced sprint interviewer for a DevSquad software factory.\n\n"
    "Your job is to help the user kick off a new sprint. Listen to their project idea and\n"
    "extract the following fields as a **valid JSON object** with NO other text before or after:\n\n"
    "{\n"
    '  "project_id": "kebab-case-machine-friendly-id-derived-from-the-title",\n'
    '  "title": "Short human-readable project title",\n'
    '  "requirement": "The user\'s full north-star description, preserved verbatim or lightly cleaned",\n'
    '  "context": "Any additional context the user provided (team, constraints, preferences, etc.)",\n'
    '  "summary": "One-sentence summary of what this sprint will build"\n'
    "}\n\n"
    "Rules:\n"
    "- project_id must be lowercase kebab-case, max 40 chars, no special chars\n"
    "- If the user provides a file path, treat the file contents as their requirement\n"
    "- If a reference document is provided alongside the north star, read it carefully as\n"
    "  detailed technical/domain context. Ask clarifying follow-up questions about anything\n"
    "  unclear by returning JSON with only an 'ask' key:\n"
    '  {"ask": "What specific question?"}\n'
    "- If the user is vague, ask clarifying questions by returning JSON with only an 'ask' key:\n"
    '  {"ask": "What specific question?"}\n'
    "- Output ONLY valid JSON, nothing else - no markdown fences, no commentary"
)


def extract_sprint_params(
    user_input: str,
    file_context: str = "",
    reference_context: str = "",
    llm_callable: Callable[[str], str] | None = None,
) -> dict[str, Any] | None:
    """Extract structured sprint parameters from a user's north-star description.

    Calls the LLM with the extraction prompt and returns the parsed JSON dict
    with keys ``project_id``, ``title``, ``requirement``, ``context``, ``summary``.

    Returns ``None`` if the LLM is unavailable or the response cannot be parsed.

    Parameters
    ----------
    user_input:
        The user's north-star description of what they want to build.
    file_context:
        Optional file contents to include as additional context.
    reference_context:
        Optional reference document content with detailed specs. The LLM is
        instructed to read this and ask follow-up questions if anything is unclear.
    llm_callable:
        Override the LLM callable.  Defaults to the system's ``_llm_complete``.
    """
    llm = llm_callable or _llm_complete
    if llm is None:
        return None

    file_block = ""
    if file_context:
        file_block = f"\nThe user also provided a file with this content:\n\n{file_context}\n"

    ref_block = ""
    if reference_context:
        ref_block = (
            f"\nThe user also provided a reference document with detailed "
            f"specifications:\n\n{reference_context}\n"
            f"Read it carefully and ask follow-ups about anything unclear.\n"
        )

    user_prompt = (
        f"The user said:\n\n{user_input}\n{file_block}\n{ref_block}\n"
        f"Extract the structured sprint parameters as JSON."
    )

    full_prompt = (
        f"<system>{_EXTRACTION_SYSTEM_PROMPT}</system>\n\n<user>{user_prompt}</user>"
    )
    raw = llm(full_prompt)

    # Try to extract JSON from the response (strip markdown fences if present)
    json_str = raw.strip()
    if json_str.startswith("```"):
        json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
        json_str = re.sub(r"\s*```$", "", json_str)

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        print(
            f"  [WARN] Could not parse LLM response as JSON. Raw response:\n"
            f"  {raw[:500]}",
            file=sys.stderr,
        )
        return None


def _confirm_and_launch(parsed: dict[str, Any]) -> bool:
    """Display the sprint summary and ask the user to confirm.

    Returns ``True`` if the user confirms.
    """
    print()
    print("  Here's what I've prepared:")
    print(f"    Project ID:  {parsed.get('project_id', '?')}")
    print(f"    Title:       {parsed.get('title', '?')}")
    print(f"    Summary:     {parsed.get('summary', '?')}")
    if parsed.get("context"):
        print(f"    Context:     {parsed.get('context', '')[:120]}")
    print()

    try:
        confirm = input("  Shall I start this sprint? (Y/n): ").strip().lower()
    except EOFError:
        confirm = "y"  # default to yes in non-interactive mode
    return confirm not in ("n", "no")


def kickoff_sprint(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Kick off the pipeline via PipelineDriver and return results.

    Parameters
    ----------
    parsed:
        Dict with keys ``project_id``, ``title``, ``requirement``, ``context``
        (as returned by :func:`extract_sprint_params`).

    Returns
    -------
    List of result dicts, one per workflow that ran.
    """
    project_id = parsed.get("project_id", "unnamed")
    requirement = parsed.get("requirement", "")

    # ── Detect existing artifacts for iterative sprints ──────────────
    project_dir = _PROJECTS_ROOT / project_id
    iteration_number = 1
    sprint_context = ""

    if project_dir.exists():
        iteration_number = 2
        existing_parts: list[str] = [
            f"This is an incremental sprint (iteration {iteration_number}).",
            f"Previous work exists at: {project_dir}",
            "",
            "Build on top of the existing code — read existing files before creating",
            "or modifying. Do NOT rewrite from scratch unless absolutely necessary.",
            "",
        ]
        # Read existing artifacts
        for artifact_name, filename in [
            ("PRD", "prd.md"),
            ("Solution", "solution.md"),
            ("Delivery Plan", "delivery_plan.json"),
        ]:
            artifact_path = project_dir / filename
            if artifact_path.exists():
                content = artifact_path.read_text(encoding="utf-8")
                existing_parts.append(f"--- Existing {artifact_name} ---")
                existing_parts.append(content)
                existing_parts.append("")

        sprint_context = "\n".join(existing_parts)

    # Publish the event first so the EventBus / TriggerRouter
    # maps the event for any external listeners.
    bus = get_event_bus()
    bus.publish(
        "sprint.init",
        payload={
            "project_id": project_id,
            "title": parsed.get("title", ""),
            "requirement": requirement,
            "context": parsed.get("context", ""),
            "sprint_context": sprint_context,
            "iteration_number": iteration_number,
        },
    )

    from src.agent.composition_root import (
        _execute_tool_inline,
        _strategy_router,
        _workflow_engine,
        prompt_registry,
    )
    from src.devsquad.pipeline_driver import PipelineDriver

    driver = PipelineDriver(
        engine=_workflow_engine,
        strategy_router=_strategy_router,
        inline_tool_executor=_execute_tool_inline,
        prompt_registry=prompt_registry,
    )
    results = driver.run_pipeline(
        initial_payload={
            "project_id": project_id,
            "title": parsed.get("title", ""),
            "requirement": requirement,
            "context": parsed.get("context", ""),
            "sprint_context": sprint_context,
            "iteration_number": iteration_number,
        },
    )
    return results


def _print_success(parsed: dict[str, Any], results: list[dict[str, Any]]) -> None:
    """Print a summary of pipeline results."""
    import textwrap

    project_id = parsed.get("project_id", "unnamed")
    print()
    print(f"  Sprint complete! Project: {project_id}")
    print(f"  Artifacts at: {_PROJECTS_ROOT / project_id}")
    print()

    if not results:
        print("  [WARN] No workflows were executed.")
        print()
        return

    for r in results:
        wf = r.get("workflow_id", "?")
        st = r.get("status", "?")
        icon = "[OK]" if st == "completed" else "[FAIL]"
        print(f"  {icon} {wf:<30s} {st}")
        if st == "completed" and r.get("result"):
            summary = r["result"]
            if len(summary) > 80:
                summary = textwrap.shorten(summary, width=80, placeholder="...")
            print(f"        -> {summary}")
        if st == "failed" and r.get("error"):
            print(f"        ! {r['error']}")
    print()
    print(f"  All artifacts saved under {_PROJECTS_ROOT / project_id}")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_interview(
    *,
    json_input: str | None = None,
    auto_confirm: bool = False,
) -> dict[str, Any] | None:
    """Run the sprint interview and pipeline.

    Two modes:

    * **Interactive** (``json_input=None``, the default) — displays the full
      conversational banner, collects user input interactively, confirms,
      launches the pipeline, and prints a summary to stdout.

    * **Non-interactive / JSON** (``json_input`` given) — skips all prompts.
      ``json_input`` is parsed as JSON with keys:

      - ``north_star`` (required) — the project description text
      - ``project_id`` (optional) — override the machine ID
      - ``auto_confirm`` (optional, default ``True``) — skip confirmation
      - ``file_path`` (optional) — path to a .md file; its content is
        appended to ``north_star``

      When ``auto_confirm`` is true (the default in JSON mode), the sprint
      is launched immediately and the result dict (with pipeline results) is
      returned.

    Parameters
    ----------
    json_input:
        JSON string with the fields described above.  When *None*, runs the
        full interactive interview.
    auto_confirm:
        Only used in interactive mode.  If true, skips the "Shall I start?"
        confirmation prompt.  Defaults to false.

    Returns
    -------
    In JSON mode, returns a dict with keys ``success``, ``project_id``,
    ``results`` (list of workflow results).  In interactive mode, returns
    ``None``.
    """
    # ── JSON (non-interactive) mode ──────────────────────────────────
    if json_input is not None:
        return _run_json_mode(json_input)

    # ── Interactive mode ─────────────────────────────────────────────
    _ensure_inbox()

    # Collect user input
    user_input = _collect_user_input()

    # Ask if the user has a reference document with detailed specs
    reference_context = ""
    try:
        print()
        print("  Do you have a reference document with more detailed specs?")
        print("  (Path to a .md file, or press Enter to skip)")
        ref_path = input("> ").strip()
        if ref_path:
            candidate = Path(ref_path)
            if not candidate.is_absolute():
                candidate = _INBOX_DIR / ref_path
            if candidate.exists():
                reference_context = candidate.read_text(encoding="utf-8")
                _print_section("Reference document loaded", f"{candidate.name} ({len(reference_context)} chars)")
            else:
                print(f"  [WARN] File not found: {ref_path}. Skipping reference doc.")
    except EOFError:
        pass

    # Call LLM to extract structured fields
    parsed = extract_sprint_params(user_input, reference_context=reference_context)

    # Handle LLM unavailability -- fallback to manual input
    if parsed is None:
        parsed = _manual_fallback(user_input)

    # Handle LLM asking a clarifying question
    if parsed and "ask" in parsed:
        print(f"\n  Clarification needed: {parsed['ask']}")
        try:
            additional = input("  > ")
        except EOFError:
            additional = ""
        user_input = f"{user_input}\n\n(Clarification: {additional})"
        parsed = extract_sprint_params(user_input)
        if parsed is None:
            parsed = _manual_fallback(user_input)

    # Handle parsing failure
    if parsed is None or "project_id" not in parsed:
        print("\n  [ERROR] Could not extract sprint parameters. Let me ask directly.\n")
        parsed = _manual_fallback(user_input)
        if parsed is None:
            print("  Aborting.")
            return None

    # Confirm with user
    confirmed = True
    if not auto_confirm:
        confirmed = _confirm_and_launch(parsed)

    if not confirmed:
        print("\n  Sprint cancelled.")
        # Offer to save the draft as a file for later
        try:
            save = input("  Save draft to inbox for later? (y/N): ").strip().lower()
        except EOFError:
            save = "n"
        if save in ("y", "yes"):
            draft_path = _INBOX_DIR / f"{parsed.get('project_id', 'draft')}.md"
            draft_path.write_text(
                f"# {parsed.get('title', 'Untitled')}\n\n"
                f"{parsed.get('requirement', '')}\n\n"
                f"## Context\n\n{parsed.get('context', '')}\n",
                encoding="utf-8",
            )
            print(f"  Saved to {draft_path}")
        return None

    # Kick off pipeline
    results = kickoff_sprint(parsed)

    # Print success
    _print_success(parsed, results)
    return None


def _run_json_mode(json_input: str) -> dict[str, Any]:
    """Non-interactive JSON mode — parse input, auto-launch, return results."""
    try:
        payload = json.loads(json_input)
    except json.JSONDecodeError as exc:
        print(json.dumps({"success": False, "error": f"Invalid JSON: {exc}"}))
        return {"success": False, "error": f"Invalid JSON: {exc}"}

    north_star = payload.get("north_star", "")
    if not north_star:
        err = "Missing 'north_star' key in JSON payload"
        print(json.dumps({"success": False, "error": err}))
        return {"success": False, "error": err}

    auto = payload.get("auto_confirm", True)
    project_id_override = payload.get("project_id")

    # Handle optional file_path — read and append to north_star
    file_path = payload.get("file_path")
    file_content = ""
    if file_path:
        fp = Path(file_path)
        if fp.exists():
            file_content = fp.read_text(encoding="utf-8")
            north_star = f"{north_star}\n\n(File contents from {file_path}:\n{file_content})"

    # Handle optional reference_doc — detailed spec that LLM reads and asks follow-ups about
    reference_doc_path = payload.get("reference_doc")
    reference_content = ""
    if reference_doc_path:
        rp = Path(reference_doc_path)
        if rp.exists():
            reference_content = rp.read_text(encoding="utf-8")

    # Extract params via LLM
    parsed = extract_sprint_params(
        north_star, file_context=file_content, reference_context=reference_content,
    )

    if parsed is None:
        err = "LLM could not extract sprint parameters. Use interactive mode."
        print(json.dumps({"success": False, "error": err}))
        return {"success": False, "error": err}

    if "ask" in parsed:
        err = f"LLM needs clarification: {parsed['ask']}. Use interactive mode."
        print(json.dumps({"success": False, "error": err}))
        return {"success": False, "error": err}

    # Override project_id if provided
    if project_id_override:
        parsed["project_id"] = project_id_override

    # Kick off pipeline
    results = kickoff_sprint(parsed)

    output = {
        "success": True,
        "project_id": parsed.get("project_id", "unnamed"),
        "title": parsed.get("title", ""),
        "summary": parsed.get("summary", ""),
        "results": results,
    }
    print(json.dumps(output, indent=2))
    return output


def _manual_fallback(user_input: str) -> dict[str, Any] | None:
    """Fallback when LLM is unavailable -- ask the user directly."""
    try:
        print()
        print("  [LLM unavailable -- collecting details directly]")
        project_id = input("  Project ID (kebab-case, e.g. 'my-cli-tool'): ").strip()
        if not project_id:
            return None
        title = input("  Project title: ").strip() or project_id
        requirement = input("  Requirement (paste your north star): ").strip() or user_input
        context = input("  Context (optional): ").strip()
    except EOFError:
        return None
    return {
        "project_id": project_id,
        "title": title,
        "requirement": requirement,
        "context": context,
        "summary": f"Sprint for {title}",
    }


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_interview()
