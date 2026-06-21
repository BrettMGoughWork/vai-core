"""
e2e_harness.py — End-to-End Prompt → LLM → Planner → Skill Harness (3.18.3)
===========================================================================

A developer harness that sends a prompt through a real LLM, which discovers
skills via S3Adapter, creates a plan via SubgoalPlanner, and executes
referenced skills through the S3 SkillRunner.

The full trace is observable:
  prompt → LLM plan JSON → discovered skills → plan steps → skill execution → results

Usage:
    python tools/testing_harness/e2e_harness.py "echo hello world"
    python tools/testing_harness/e2e_harness.py "list files in the current directory"
    python tools/testing_harness/e2e_harness.py "read the first 10 lines of README.md"
"""

from __future__ import annotations

import importlib
import json
import re
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Ensure project root is on the path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(override=True)


# ══════════════════════════════════════════════════════════════════════════════
# Embedding function (deterministic character-bucket hash)
# ══════════════════════════════════════════════════════════════════════════════


from src.capabilities.discovery.providers.mock_provider import _simple_embedding_fn


# ══════════════════════════════════════════════════════════════════════════════
# Primitive auto-discovery (delegates to canonical source loader)
# ══════════════════════════════════════════════════════════════════════════════


def load_all_primitives(registry) -> int:
    """Auto-discover all stdlib primitives and register them.

    Delegates to the canonical loader in ``src.capabilities.primitives.stdlib``.

    Returns the count of registered primitives.
    """
    from src.capabilities.primitives.stdlib import load_all_primitives as _load

    return _load(registry)


# ══════════════════════════════════════════════════════════════════════════════
# Skill loading (delegates to canonical source loader)
# ══════════════════════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════════════════════
# E2E Harness
# ══════════════════════════════════════════════════════════════════════════════

SEP = "=" * 72
MINOR = "-" * 48


@dataclass
class HarnessResult:
    """Result of an e2e harness run."""
    success: bool
    prompt: str
    plan_id: str | None = None
    plan_intent: str | None = None
    target_skill: str | None = None
    discovered_skills: list[str] = field(default_factory=list)
    plan_steps: list[dict] = field(default_factory=list)
    execution_results: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_ms: int = 0


def run_e2e(prompt: str, backend: str = "real_llm", verbose: bool = True) -> HarnessResult:
    """Run the full e2e pipeline: prompt → LLM → planner → skills → execution.

    Args:
        prompt: The user's natural-language prompt.
        backend: "real_llm" (live LLM) or "mock" (deterministic mock).
        verbose: If True, print progress to stdout. If False, suppress.

    Returns:
        HarnessResult with full trace data.
    """
    _out = print if verbose else (lambda *a, **kw: None)
    result = HarnessResult(success=False, prompt=prompt)
    t0 = time.time()

    try:
        # ── 1. Wire up PrimitiveRegistry ──────────────────────────────────
        from src.capabilities.registry.primitive_registry import PrimitiveRegistry
        prim_registry = PrimitiveRegistry()
        prim_count = load_all_primitives(prim_registry)

        _out(f"{MINOR} PRIMITIVES {MINOR}")
        _out(f"  Loaded: {prim_count} primitives")

        # ── 2. Wire up primitives (skills removed; only primitives remain) ──
        # SkillRegistry, SkillRunner, SkillAuthor all removed in Phase 4 clean sweep.
        # Only PrimitiveRegistry is needed for primitive execution.

        # ── 4. Wire up MemoryGovernance ──────────────────────────────────
        from src.strategy.memory.segment_memory import SegmentMemory
        from src.strategy.memory.subgoal_memory import SubgoalMemory
        from src.strategy.memory.plan_memory import PlanMemory
        from src.strategy.memory.drift_memory import DriftMemory
        from src.strategy.memory.governance.memory_governance import MemoryGovernance

        segment_memory = SegmentMemory()
        subgoal_memory = SubgoalMemory()
        plan_memory = PlanMemory()
        drift_memory = DriftMemory()
        governance = MemoryGovernance(
            subgoal_memory, segment_memory, plan_memory, drift_memory,
        )

        # ── 5. Wire up LLM ───────────────────────────────────────────────
        if backend == "mock":
            from src.runtime.llm.mock_llm import MockLLM
            llm = MockLLM()
            model = "mock"
        else:
            from src.runtime.llm.llm_factory import factory
            provider = os.environ.get("LLM_PROVIDER", "deepseek")
            model = os.environ.get("LLM_MODEL", "deepseek-chat")
            llm = factory.create(provider, model)

        # ── 6. Wire up SubgoalPlanner ────────────────────────────────────
        from src.strategy.planning.generator.subgoal_planner import SubgoalPlanner

        def _llm_complete(sys_prompt: str, user_msg: str) -> str:
            raw = llm.chat(model=model, messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_msg},
            ])
            return raw["choices"][0]["message"]["content"]

        planner = SubgoalPlanner(llm_complete=_llm_complete)

        # ── 7. Register subgoal + generate plan ──────────────────────────
        from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState
        from src.strategy.types.hashing import stable_hash

        subgoal_id = stable_hash({"prompt": prompt, "harness": "e2e"})
        timestamp = "2025-01-01T00:00:00Z"

        subgoal_memory.put(Subgoal(
            subgoal_id=subgoal_id,
            goal=prompt,
            context={"source": "e2e_harness"},
            metadata={},
            parent_id=None,
            state=SubgoalLifecycleState.ACTIVE,
            created_at=1704067200000,
        ))

        _out(f"\n{MINOR} LLM PLANNING {MINOR}")
        _out(f"  Prompt: {prompt}")
        _out(f"  Calling LLM ({backend}:{model}) ...")

        plan_id = planner.plan_for_subgoal(
            subgoal_id=subgoal_id,
            goal=prompt,
            governance=governance,
            timestamp=timestamp,
            skill_refs=[],
        )
        result.plan_id = plan_id

        # ── 8. Read the generated plan ───────────────────────────────────
        plan_record = plan_memory.get_record(plan_id)
        if plan_record is None:
            result.errors.append("Plan record not found after generation")
            return result

        result.plan_intent = plan_record.intent
        result.target_skill = plan_record.targetskillid

        segment_ids = plan_memory.get_segments(plan_id)
        if segment_ids:
            seg = governance.get_segment(segment_ids[0])
            if seg is not None:
                result.discovered_skills = seg.skills or []
                seg_step_ids = seg.context.get("step_ids", [])
                seg_capabilities = seg.context.get("capabilities", [])
                seg_inputs = seg.context.get("step_inputs", [])
                result.plan_steps = [
                    {
                        "id": seg_step_ids[i] if i < len(seg_step_ids) else f"step-{i}",
                        "description": seg.steps[i],
                        "capability": seg_capabilities[i] if i < len(seg_capabilities) else "",
                        "inputs": seg_inputs[i] if i < len(seg_inputs) else {},
                    }
                    for i in range(len(seg.steps))
                ]

        _out(f"  Plan ID:     {plan_id[:32]}...")
        _out(f"  Intent:      {result.plan_intent}")
        _out(f"  Target skill:{result.target_skill}")
        _out(f"  Discovered:  {result.discovered_skills}")
        _out(f"  Steps:       {len(result.plan_steps)}")

        # ── 9. Execute plan steps (SkillRunner removed in Phase 4 clean sweep) ─
        _out(f"\n{MINOR} SKILL EXECUTION (legacy, disabled) {MINOR}")
        _out(f"  SkillRunner removed in Phase 4 clean sweep. No execution performed.\n")

        # ── 10. Determine overall success ────────────────────────────────
        result.success = bool(result.plan_id)

    except Exception as exc:
        import traceback
        result.errors.append(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        result.elapsed_ms = int((time.time() - t0) * 1000)

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Pretty-printer
# ══════════════════════════════════════════════════════════════════════════════


def print_summary(result: HarnessResult) -> None:
    """Pretty-print the full e2e trace."""
    print(f"\n{SEP}")
    print(f"  E2E HARNESS SUMMARY")
    print(SEP)

    print(f"\n  Prompt:        {result.prompt}")
    print(f"  Plan ID:       {result.plan_id}")
    print(f"  Intent:        {result.plan_intent}")
    print(f"  Target skill:  {result.target_skill}")

    print(f"\n  Discovered skills ({len(result.discovered_skills)}):")
    for sk in result.discovered_skills:
        print(f"    • {sk}")

    print(f"\n  Plan steps ({len(result.plan_steps)}):")
    for i, step in enumerate(result.plan_steps):
        print(f"    [{i}] {step.get('id', '?')}: {step.get('description', '?')}")

    print(f"\n  Execution results ({len(result.execution_results)}):")
    all_ok = True
    for r in result.execution_results:
        status = "PASS" if r["success"] else "FAIL"
        if not r["success"]:
            all_ok = False
        output_str = json.dumps(r.get("output"), default=str)[:100] if r.get("output") else "(none)"
        print(f"    [{status}] step {r['step_index']}: {r['skill_name']} -> {output_str}")
        if r.get("error"):
            print(f"           error: {r['error']}")

    if result.errors:
        print(f"\n  Errors ({len(result.errors)}):")
        for err in result.errors:
            print(f"    !! {err}")

    print(f"\n  Elapsed: {result.elapsed_ms} ms")
    overall = "PASSED" if result.success else "FAILED"
    print(f"  Overall: {overall}")
    print(SEP)


# ══════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="E2E harness: prompt → LLM → planner → skills → execution (3.18.3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/testing_harness/e2e_harness.py "echo hello world"
  python tools/testing_harness/e2e_harness.py "list files in the current directory"
  python tools/testing_harness/e2e_harness.py --backend mock "echo test"
        """,
    )
    parser.add_argument(
        "prompt",
        type=str,
        help="Natural-language prompt to send through the full pipeline",
    )
    parser.add_argument(
        "--backend",
        type=str,
        choices=["real_llm", "mock"],
        default="real_llm",
        help="LLM backend (default: real_llm)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output result as JSON instead of pretty-printed",
    )
    args = parser.parse_args()

    result = run_e2e(prompt=args.prompt, backend=args.backend, verbose=not args.json_output)

    if args.json_output:
        print(json.dumps({
            "success": result.success,
            "prompt": result.prompt,
            "plan_id": result.plan_id,
            "plan_intent": result.plan_intent,
            "target_skill": result.target_skill,
            "discovered_skills": result.discovered_skills,
            "plan_steps": result.plan_steps,
            "execution_results": [
                {k: v for k, v in r.items() if v is not None}
                for r in result.execution_results
            ],
            "errors": result.errors,
            "elapsed_ms": result.elapsed_ms,
        }, indent=2, default=str))
    else:
        print_summary(result)

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
