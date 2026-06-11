"""
Phase 2.14.7 — Minimal S1 -> LLM -> S1 PromptResponse Round-Trip Test
====================================================================

Smallest safe integration point: proves the LLM can produce a valid
PromptResponse when asked explicitly with a schema-guided prompt.

No S2 logic. No planning. No cycles. No substrate.

Run manually:
    python tests/manual/test_llm_prompt_response_minimal.py
"""

from __future__ import annotations

import json
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv

load_dotenv(override=True)

from src.strategy.planning.s1_contract import s1_real_client
from src.strategy.planning.s1_contract.types import PromptRequest
from src.strategy.planning.s1_contract.s1_client import call_s1_backend
from src.strategy.planning.s1_contract.s1_prompt_builder import build_llm_prompt
from src.strategy.planning.s1_contract.s1_response_validator import validate_llm_response


def test_llm_prompt_response_minimal():
    """Minimal PromptResponse round-trip through the real LLM."""

    # 1. Build the simplest possible PromptRequest
    request = PromptRequest(
        prompt={"instruction": "Produce a valid PromptResponse JSON object."},
        memory={},
        plan_context={
            "subgoal": {"index": 0, "state": "pending", "description": "test subgoal"},
            "segment": {"index": 0, "state": "pending", "description": "test segment"},
        },
        tool_context=[],
    )

    # 2. Enable the real LLM kill-switch (restore after test to avoid
    #    contaminating other tests that expect the stub path)
    _prev_enable = s1_real_client.ENABLE_REAL_LLM
    s1_real_client.ENABLE_REAL_LLM = True
    try:

        # 3. Call the real LLM backend
        result = call_s1_backend(request, backend="real_llm")
    finally:
        s1_real_client.ENABLE_REAL_LLM = _prev_enable

    # 4. Print trace for inspection
    print("=" * 72)
    print("S1 -> LLM -> S1 MINIMAL ROUND-TRIP TEST")
    print("=" * 72)

    # Show what the prompt payload looked like (built from the request)
    prompt_payload = build_llm_prompt(request)
    print("\n-- PROMPT PAYLOAD KEYS --")
    print(json.dumps(list(prompt_payload.keys()), indent=2))
    print(f"\n  system_instruction length: {len(prompt_payload.get('system_instruction', ''))} chars")
    schema_req = prompt_payload.get('response_schema', {}).get('required', [])
    print(f"  response_schema required fields: {len(schema_req)}")
    print(f"  valid_examples: {len(prompt_payload.get('valid_examples', []))}")
    print(f"  invalid_examples: {len(prompt_payload.get('invalid_examples', []))}")

    print("\n-- RESULT --")
    print(f"  Type: {type(result).__name__}")

    if hasattr(result, "type"):
        # S1Error
        print(f"  Error type: {result.type}")
        print(f"  Error message: {result.message}")
        if hasattr(result, "details"):
            details = result.details
            if "raw_preview" in details:
                print(f"  Raw preview: {details['raw_preview'][:500]}")
            if "missing_fields" in details:
                print(f"  Missing fields: {details['missing_fields']}")
            if "received_fields" in details:
                print(f"  Received fields: {details['received_fields']}")
            if "type_errors" in details:
                print(f"  Type errors: {details['type_errors'][:5]}")
        print("\n  FAILED: S1Error returned instead of PromptResponse")
        print("  This means either the prompt was malformed or the LLM output was invalid.")
        return False

    # PromptResponse
    output = result.output if hasattr(result, "output") else {}
    print(f"  drift_detected: {output.get('drift_detected')}")
    print(f"  drift_type: {output.get('drift_type')}")
    print(f"  drift_severity: {output.get('drift_severity')}")
    print(f"  progress: {output.get('progress')}")
    print(f"  is_complete: {output.get('is_complete')}")
    print(f"  confidence: {output.get('confidence')}")
    print(f"  next_action: {output.get('next_action')}")
    print(f"  repairs count: {len(output.get('repairs', []))}")
    print(f"  blockers count: {len(output.get('blockers', []))}")
    print(f"  shaped: {output.get('shaped')}")

    # 5. Assert validity
    required = [
        "drift_detected", "drift_type", "drift_severity", "drift_detail",
        "repairs", "quality", "structural_deviation", "progress",
        "is_complete", "confidence", "next_action", "blockers",
        "shaped", "steps", "segments",
    ]
    missing = [k for k in required if k not in output]
    if missing:
        print(f"\n  FAILED: Missing required fields: {missing}")
        return False

    # Type checks
    type_issues = []
    if not isinstance(output.get("drift_detected"), bool):
        type_issues.append("drift_detected not bool")
    if not isinstance(output.get("drift_detail"), list):
        type_issues.append("drift_detail not list")
    if not isinstance(output.get("repairs"), list):
        type_issues.append("repairs not list")
    if not isinstance(output.get("progress"), (int, float)):
        type_issues.append("progress not number")
    if not isinstance(output.get("is_complete"), bool):
        type_issues.append("is_complete not bool")
    if not isinstance(output.get("confidence"), (int, float)):
        type_issues.append("confidence not number")

    if type_issues:
        print(f"\n  FAILED: Type issues: {type_issues}")
        return False

    print("\nPASSED: LLM produced a valid PromptResponse")
    return True


if __name__ == "__main__":
    success = test_llm_prompt_response_minimal()
    sys.exit(0 if success else 1)
