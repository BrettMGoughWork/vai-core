"""
Phase 2.14.7 — Tiny S2 Plan Test (1 subgoal, 1 segment, 1 cycle, real LLM)
===========================================================================

Smallest S2 integration test with the real LLM backend. Proves:
  1. S2 plan → PromptRequest → LLM → PromptResponse → S2 updates
  2. The full round-trip works for one cycle
  3. No crashes, structured errors if any, S2 contract intact

No multi-cycle. No planning. No drift/repair/reflection logic (S2's job).

Run manually:
    python tests/manual/test_tiny_s2_plan_real_llm.py
"""

from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv(override=True)

from src.core.planning.s1_contract import s1_real_client
from src.core.planning.s1_contract.types import PromptResponse, S1Error
from src.core.planning.s1_contract.s1_client import call_s1_backend
from src.core.planning.s1_contract.s2_to_s1_adapter import build_prompt_request
from src.core.planning.s1_contract.s1_to_s2_adapter import parse_prompt_response
from src.core.planning.s1_contract.validators import (
    validate_prompt_request,
    validate_prompt_response,
)

from tests.e2e.helpers import plan_1_1


# ── Fake S2 state objects (mirror test_s1_s2_smoke.py pattern) ────────────

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


def _make_fake_memory():
    return {
        "subgoal_history": [],
        "segment_history": [],
        "drift_history": [],
        "repair_history": [],
    }


# ── Test ──────────────────────────────────────────────────────────────────


def test_tiny_s2_plan_real_llm():
    """1 subgoal, 1 segment, 1 cycle through the real LLM backend."""

    print("=" * 72)
    print("TINY S2 PLAN TEST — 1 subgoal, 1 segment, 1 cycle, real LLM")
    print("=" * 72)

    # 1. Build the minimal plan
    subgoals, segments = plan_1_1()
    print(f"\n-- PLAN --")
    for sg in subgoals:
        print(f"  Subgoal: {sg.subgoal_id} — {sg.goal}")
    for seg in segments:
        print(f"  Segment: {seg.segment_id} — steps: {seg.steps}")

    # 2. Build the PromptRequest from fake S2 state
    agent_state = _FakeAgentState(cycle=0, is_complete=False)
    subgoal_state = _FakeSubgoalState(index=0, state="active")
    segment_state = _FakeSegmentState(index=0, state="running")
    memory = _make_fake_memory()

    request = build_prompt_request(
        agent_state=agent_state,
        subgoal_state=subgoal_state,
        segment_state=segment_state,
        memory=memory,
    )

    # Validate the request before sending
    assert validate_prompt_request(request), "PromptRequest failed validation"
    print(f"\n-- PROMPT REQUEST --")
    print(f"  instruction: {request.prompt.get('instruction', '')[:120]}...")
    print(f"  agent_cycle: {request.prompt.get('agent_cycle')}")
    print(f"  plan_context keys: {list(request.plan_context.keys())}")

    # 3. Enable the real LLM kill-switch (restore after test to avoid
    #    contaminating other tests that expect the stub path)
    _prev_enable = s1_real_client.ENABLE_REAL_LLM
    s1_real_client.ENABLE_REAL_LLM = True
    try:

        # 4. Call the real LLM backend (S2 → S1)
        print(f"\n-- CALLING S1 BACKEND (real_llm) --")
        response = call_s1_backend(request, backend="real_llm")
    finally:
        s1_real_client.ENABLE_REAL_LLM = _prev_enable

    print(f"  Response type: {type(response).__name__}")

    # 5. Handle S1Error (kill-switch, validation failure, etc.)
    if isinstance(response, S1Error):
        print(f"\n-- S1 ERROR --")
        print(f"  type: {response.type}")
        print(f"  message: {response.message}")
        if hasattr(response, "details") and response.details:
            for k, v in response.details.items():
                if isinstance(v, str) and len(v) > 500:
                    v = v[:500] + "..."
                print(f"  {k}: {v}")
        print(f"\n  FAILED: Got S1Error — the LLM round-trip was not clean.")
        return False

    # 6. Got a PromptResponse — validate and parse
    assert isinstance(response, PromptResponse), f"Expected PromptResponse, got {type(response)}"

    print(f"\n-- PROMPT RESPONSE (S1 → S2) --")
    output = response.output if hasattr(response, "output") else {}
    fields = [
        "drift_detected", "drift_type", "drift_severity",
        "progress", "is_complete", "confidence", "next_action",
        "shaped", "quality", "structural_deviation",
    ]
    for f in fields:
        val = output.get(f)
        if isinstance(val, str) and len(val) > 120:
            val = val[:120] + "..."
        print(f"  {f}: {val}")
    print(f"  repairs count: {len(output.get('repairs', []))}")
    print(f"  blockers count: {len(output.get('blockers', []))}")
    print(f"  steps count: {len(output.get('steps', []))}")
    print(f"  segments count: {len(output.get('segments', []))}")

    # Validate PromptResponse against schema
    is_valid = validate_prompt_response(response)
    if not is_valid:
        print(f"\n  FAILED: PromptResponse schema validation failed")
        return False
    print(f"  PromptResponse schema validation: PASSED")

    # 7. Parse into S2 updates (S1 → S2 adapter)
    s2_updates = parse_prompt_response(response)
    print(f"\n-- S2 UPDATES --")
    print(f"  keys: {list(s2_updates.keys())}")
    for k, v in s2_updates.items():
        if isinstance(v, list):
            print(f"  {k}: [{len(v)} items]")
        elif isinstance(v, dict):
            print(f"  {k}: {{{len(v)} keys}} → {json.dumps(v, default=str)[:200]}")
        else:
            val_str = str(v)
            if len(val_str) > 200:
                val_str = val_str[:200] + "..."
            print(f"  {k}: {val_str}")

    # 8. Assertions
    print(f"\n-- ASSERTIONS --")
    passed = True

    # A. No crashes
    print(f"  ✓ No crashes (reached end of test)")

    # B. Response is valid PromptResponse
    assert isinstance(response, PromptResponse), "Not a PromptResponse"
    print(f"  ✓ Response is PromptResponse")

    # C. Schema validation passed
    assert is_valid, "Schema validation failed"
    print(f"  ✓ Schema validation passed")

    # D. S2 updates are a dict
    assert isinstance(s2_updates, dict), f"Expected dict, got {type(s2_updates)}"
    print(f"  ✓ S2 updates is dict")

    # E. No raw strings in updates (quick check)
    for k, v in s2_updates.items():
        if isinstance(v, str) and len(v) > 500:
            print(f"  ✗ Raw string detected in s2_updates['{k}']: {len(v)} chars")
            passed = False
    if passed:
        print(f"  ✓ No raw strings in S2 updates")

    # F. If errors present, they must be structured
    if "error" in s2_updates:
        err = s2_updates["error"]
        if isinstance(err, dict):
            has_type = "type" in err or "error_type" in err
            has_msg = "message" in err
            if has_type and has_msg:
                print(f"  ✓ Error is structured: type={err.get('type')}, message={err.get('message')[:80]}")
            else:
                print(f"  ✗ Error missing type/message: {err}")
                passed = False
        else:
            print(f"  ✗ Error not a dict: {type(err)}")
            passed = False

    # G. Key fields present in output
    required_output = [
        "drift_detected", "drift_type", "drift_severity", "drift_detail",
        "repairs", "quality", "structural_deviation", "progress",
        "is_complete", "confidence", "next_action", "blockers",
        "shaped", "steps", "segments",
    ]
    missing_output = [k for k in required_output if k not in output]
    if missing_output:
        print(f"  ✗ Missing required output fields: {missing_output}")
        passed = False
    else:
        print(f"  ✓ All {len(required_output)} required output fields present")

    # H. Type checks
    type_ok = True
    if not isinstance(output.get("drift_detected"), bool):
        print(f"  ✗ drift_detected not bool: {type(output.get('drift_detected'))}")
        type_ok = False
    if not isinstance(output.get("drift_detail"), list):
        print(f"  ✗ drift_detail not list: {type(output.get('drift_detail'))}")
        type_ok = False
    if not isinstance(output.get("repairs"), list):
        print(f"  ✗ repairs not list")
        type_ok = False
    if not isinstance(output.get("progress"), (int, float)):
        print(f"  ✗ progress not number: {type(output.get('progress'))}")
        type_ok = False
    if not isinstance(output.get("is_complete"), bool):
        print(f"  ✗ is_complete not bool: {type(output.get('is_complete'))}")
        type_ok = False
    if not isinstance(output.get("confidence"), (int, float)):
        print(f"  ✗ confidence not number: {type(output.get('confidence'))}")
        type_ok = False
    if type_ok:
        print(f"  ✓ All type checks passed")

    if passed and type_ok:
        print(f"\n{'=' * 72}")
        print(f"RESULT: PASSED — S2 → S1 → S2 round-trip works with real LLM")
        print(f"{'=' * 72}")
        return True
    else:
        print(f"\n{'=' * 72}")
        print(f"RESULT: FAILED — see issues above")
        print(f"{'=' * 72}")
        return False


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    success = test_tiny_s2_plan_real_llm()
    sys.exit(0 if success else 1)
