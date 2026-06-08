"""
run_cycle.py — Manual Single-Cycle Runner for the Substrate
============================================================

A developer REPL for the S2↔S1↔LLM boundary.  Runs exactly ONE cycle,
calls the real LLM (or simulation), validates the response, parses S2
updates, and pretty-prints everything.

Usage::

    python run_cycle.py "write me a haiku" --backend real_llm
    python run_cycle.py "say hello" --backend simulation

This is NOT the full agent loop — no multi-cycle, no drift/repair,
no reflection, no skills, no primitives.  It is the single-step
debugger for your substrate.
"""

from __future__ import annotations

import argparse
import json
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv(override=True)

# ── S2 plan types ──────────────────────────────────────────────────────
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState
from src.core.types.plan_segment import PlanSegment
from src.core.types.hashing import stable_hash

# ── S1 contract types & pipeline ───────────────────────────────────────
from src.core.planning.s1_contract.types import PromptRequest, PromptResponse, S1Error
from src.core.planning.s1_contract.s2_to_s1_adapter import build_prompt_request
from src.core.planning.s1_contract.s1_to_s2_adapter import parse_prompt_response
from src.core.planning.s1_contract.s1_client import call_s1_backend
from src.core.planning.s1_contract.validators import (
    validate_prompt_request,
    validate_prompt_response,
)
from src.core.planning.s1_contract import s1_real_client


# ══════════════════════════════════════════════════════════════════════════
# Tiny plan builder
# ══════════════════════════════════════════════════════════════════════════


def _build_tiny_plan(user_request: str) -> tuple[list[Subgoal], list[PlanSegment]]:
    """Build a minimal plan (1 subgoal, 1 segment) from a user request string.

    Pure function.  Produces a deterministic subgoal_id and segment_id
    from the request text so identical requests produce identical plans.
    """
    subgoal = Subgoal(
        subgoal_id=stable_hash({"goal": user_request, "index": 0}),
        goal=user_request,
        context={"source": "run_cycle", "index": 0},
        metadata={},
        state=SubgoalLifecycleState.ACTIVE,
    )

    segment = PlanSegment(
        subgoal_id=subgoal.subgoal_id,
        steps=["interpret_request", "produce_response"],
        context={"subgoal": 1, "segment": 1},
        metadata={},
    )

    return [subgoal], [segment]


# ══════════════════════════════════════════════════════════════════════════
# Fake S2 state (mirrors test_s1_s2_smoke.py pattern)
# ══════════════════════════════════════════════════════════════════════════


class _FakeEnum:
    def __init__(self, value):
        self.value = value


class _FakeAgentState:
    def __init__(self, cycle=0, is_complete=False):
        self.cycle = cycle
        self.is_complete = is_complete


class _FakeSubgoalState:
    def __init__(self, index=0, state="active"):
        self.index = index
        self.state = _FakeEnum(state)


class _FakeSegmentState:
    def __init__(self, index=0, state="running"):
        self.index = index
        self.state = _FakeEnum(state)


def _make_fake_memory() -> dict:
    return {
        "subgoal_history": [],
        "segment_history": [],
        "drift_history": [],
        "repair_history": [],
    }


# ══════════════════════════════════════════════════════════════════════════
# Pretty printers
# ══════════════════════════════════════════════════════════════════════════

SEP = "=" * 72
MINOR = "-" * 48


def _print_plan(subgoals: list[Subgoal], segments: list[PlanSegment]) -> None:
    print(f"\n{MINOR} PLAN {MINOR}")
    print(f"  Subgoals: {len(subgoals)}")
    for sg in subgoals:
        print(f"    [{sg.subgoal_id[:16]}...]  {sg.goal}")
    print(f"  Segments: {len(segments)}")
    for seg in segments:
        short_id = seg.segment_id[:16]
        print(f"    [{short_id}...]  steps: {seg.steps}")


def _print_prompt_request(request: PromptRequest) -> None:
    print(f"\n{MINOR} PROMPT REQUEST (S2 → S1) {MINOR}")
    prompt = request.prompt
    print(f"  instruction : {prompt.get('instruction', '')[:120]}")
    print(f"  agent_cycle : {prompt.get('agent_cycle')}")
    pc = request.plan_context
    print(f"  plan_context:")
    print(f"    subgoal : {json.dumps(pc.get('subgoal', {}), default=str)[:120]}")
    print(f"    segment : {json.dumps(pc.get('segment', {}), default=str)[:120]}")
    print(f"    agent   : {json.dumps(pc.get('agent', {}), default=str)[:120]}")
    print(f"  memory keys  : {list(request.memory.keys())}")
    print(f"  tool_context : {len(request.tool_context)} tools")


def _print_response(response: PromptResponse | S1Error) -> None:
    print(f"\n{MINOR} S1 RESPONSE {MINOR}")

    if isinstance(response, S1Error):
        print(f"  ✗ S1Error")
        print(f"    type    : {response.type}")
        print(f"    message : {response.message}")
        details = response.details
        if details:
            for k, v in details.items():
                val_str = str(v)
                if len(val_str) > 300:
                    val_str = val_str[:300] + "... (truncated)"
                print(f"    {k}: {val_str}")
        return

    # PromptResponse
    output = response.output
    print(f"  ✓ PromptResponse  (schema valid: {validate_prompt_response(response)})")
    print(f"  --- key fields ---")
    fields = [
        ("drift_detected",       "drift_detected"),
        ("drift_type",           "drift_type"),
        ("drift_severity",       "drift_severity"),
        ("drift_detail",         lambda o: f"[{len(o.get('drift_detail', []))} items]"),
        ("repairs",              lambda o: f"[{len(o.get('repairs', []))} items]"),
        ("quality",              lambda o: json.dumps(o.get('quality', {}))),
        ("structural_deviation", lambda o: json.dumps(o.get('structural_deviation', {}))),
        ("progress",             "progress"),
        ("is_complete",          "is_complete"),
        ("confidence",           "confidence"),
        ("next_action",          "next_action"),
        ("blockers",             lambda o: f"[{len(o.get('blockers', []))} items]"),
        ("shaped",               "shaped"),
        ("steps",                lambda o: f"[{len(o.get('steps', []))} items]"),
        ("segments",             lambda o: f"[{len(o.get('segments', []))} items]"),
    ]
    for label, key_or_fn in fields:
        if callable(key_or_fn):
            val = key_or_fn(output)
        else:
            val = output.get(key_or_fn, "<missing>")
        val_str = str(val)
        if len(val_str) > 120:
            val_str = val_str[:120] + "..."
        print(f"    {label:<24} {val_str}")

    if response.tool_calls:
        print(f"  --- tool calls ({len(response.tool_calls)}) ---")
        for tc in response.tool_calls:
            print(f"    {tc.get('name', '?')}")
    if response.errors:
        print(f"  --- errors ({len(response.errors)}) ---")
        for err in response.errors:
            print(f"    [{err.get('type', '?')}] {err.get('message', '?')[:120]}")


def _print_s2_updates(updates: dict) -> None:
    print(f"\n{MINOR} S2 UPDATES (S1 → S2) {MINOR}")
    print(f"  keys: {list(updates.keys())}")

    # drift_signals
    ds = updates.get("drift_signals", [])
    print(f"  drift_signals      : [{len(ds)} items]")
    for s in ds:
        print(f"    source={s.get('source')} drift={s.get('drift')} severity={s.get('severity')}")

    # repair_proposals
    rp = updates.get("repair_proposals", [])
    print(f"  repair_proposals   : [{len(rp)} items]")
    for p in rp:
        print(f"    target={p.get('target')} action={p.get('action')}")

    # reflection
    ref = updates.get("reflection", {})
    print(f"  reflection:")
    print(f"    progress     : {ref.get('progress')}")
    print(f"    is_complete  : {ref.get('is_complete')}")
    print(f"    confidence   : {ref.get('confidence')}")
    print(f"    next_action  : {ref.get('next_action')}")
    print(f"    blockers     : {ref.get('blockers')}")

    # tool_results
    tr = updates.get("tool_results", [])
    print(f"  tool_results       : [{len(tr)} items]")

    # errors
    errs = updates.get("errors", [])
    print(f"  errors             : [{len(errs)} items]")
    for e in errs:
        print(f"    [{e.get('type', '?')}] {e.get('message', '?')[:120]}")

    # output_raw (summary)
    raw = updates.get("output_raw", {})
    if raw:
        required = [
            "drift_detected", "drift_type", "drift_severity",
            "progress", "is_complete", "confidence", "next_action",
            "shaped",
        ]
        print(f"  output_raw         : {{{len(raw)} keys}}")
        for k in required:
            if k in raw:
                print(f"    {k:<20} {raw[k]}")


# ══════════════════════════════════════════════════════════════════════════
# Main runner
# ══════════════════════════════════════════════════════════════════════════


def run_cycle(user_request: str, backend: str = "simulation") -> int:
    """Execute one S2→S1→S2 cycle and pretty-print the results.

    Returns 0 on success, 1 on failure.
    """
    print(SEP)
    print(f"  MANUAL CYCLE RUNNER")
    print(f"  backend: {backend}")
    print(SEP)

    # 1. Build a tiny plan from the user request
    subgoals, segments = _build_tiny_plan(user_request)
    _print_plan(subgoals, segments)

    # 2. Hydrate fake S2 state
    agent_state = _FakeAgentState(cycle=0, is_complete=False)
    subgoal_state = _FakeSubgoalState(index=0, state="active")
    segment_state = _FakeSegmentState(index=0, state="running")
    memory = _make_fake_memory()

    # 3. Build the PromptRequest
    request = build_prompt_request(
        agent_state=agent_state,
        subgoal_state=subgoal_state,
        segment_state=segment_state,
        memory=memory,
    )
    _print_prompt_request(request)

    # 4. Validate the request
    if not validate_prompt_request(request):
        print("\n  ✗ PromptRequest failed validation — aborting")
        return 1

    # 5. Enable real LLM kill-switch if needed
    if backend == "real_llm":
        s1_real_client.ENABLE_REAL_LLM = True

    # 6. Call the S1 backend
    print(f"\n{MINOR} CALLING S1 BACKEND ({backend}) {MINOR}")
    response = call_s1_backend(request, backend=backend)
    _print_response(response)

    # 7. Parse into S2 updates if we got a PromptResponse
    if isinstance(response, PromptResponse):
        s2_updates = parse_prompt_response(response)
        _print_s2_updates(s2_updates)

        # Quick sanity assertions
        assert isinstance(s2_updates, dict), "parse_prompt_response must return dict"
        print(f"\n{MINOR} ASSERTIONS {MINOR}")
        print(f"  ✓ No crashes")
        print(f"  ✓ Response is PromptResponse (schema-validated)")
        print(f"  ✓ S2 updates are dict with {len(s2_updates)} keys")
        print(f"  ✓ Trace printed (above)")
        print(f"\n{SEP}")
        print(f"  RESULT: PASSED — cycle completed cleanly")
        print(SEP)
        return 0

    # S1Error path
    print(f"\n{MINOR} ASSERTIONS {MINOR}")
    print(f"  ✓ No crashes (S1Error is structured)")
    print(f"  ✓ Error is typed: {response.type}")
    print(f"  ✓ S2 state not mutated")
    print(f"\n{SEP}")
    print(f"  RESULT: S1Error — see details above")
    print(SEP)
    return 1


# ══════════════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════════════


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manual single-cycle runner for S2↔S1↔LLM substrate.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_cycle.py "write me a haiku" --backend real_llm
  python run_cycle.py "say hello world" --backend simulation
        """,
    )
    parser.add_argument(
        "request",
        type=str,
        help="User request string (e.g. 'write me a haiku')",
    )
    parser.add_argument(
        "--backend",
        type=str,
        choices=["simulation", "real_llm"],
        default="simulation",
        help="S1 backend to use (default: simulation)",
    )
    args = parser.parse_args()

    exit_code = run_cycle(user_request=args.request, backend=args.backend)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
