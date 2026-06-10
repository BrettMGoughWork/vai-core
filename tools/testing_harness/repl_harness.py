"""
repl_harness.py — REPL test harness for the Release 0.1 S2 pipeline (2.18.6)
===========================================================================

A stdin loop that accepts user prompts, runs the full S2 pipeline
(plan → detect → repair), and remembers conversation context across turns.

This is the primary manual testing interface for Release 0.1→1.0.

Usage:
    python tools/testing_harness/repl_harness.py
    python tools/testing_harness/repl_harness.py --mock   # deterministic, no LLM

Commands (type at the `s2>` prompt):
    <any text>     — plan it, detect breakages, repair if needed
    :history       — show conversation history
    :plans         — list all generated plans
    :context       — show current conversation context
    :clear         — reset conversation context
    :help          — show this help
    :quit / :exit  — exit the REPL
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root is on the path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(override=True)

from src.core.memory.governance.memory_governance import MemoryGovernance
from src.core.memory.subgoal_memory import SubgoalMemory
from src.core.memory.segment_memory import SegmentMemory
from src.core.memory.plan_memory import PlanMemory
from src.core.memory.drift_memory import DriftMemory
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.memory.plan_memory_types import PlanMemoryRecord
from src.core.memory.drift_memory_types import DriftEvent
from src.core.memory.repair.plan_repair import PlanRepair
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState
from src.core.planning.agent_planner import AgentPlanner
from src.core.planning.models.plan import Plan
from src.core.llm.mock_llm import MockLLM


# ── Constants ────────────────────────────────────────────────────────────────

SEP = "=" * 72
PROMPT = "s2> "
HELP_TEXT = """
Commands:
  <any text>     — plan it, detect breakages, repair if needed
  :history       — show conversation history
  :plans         — list all generated plans
  :context       — show current conversation context
  :clear         — reset conversation context
  :help          — show this help
  :quit / :exit  — exit the REPL
"""


# ── Conversation context ─────────────────────────────────────────────────────

class ConversationContext:
    """Accumulates prompts, plans, and repair outcomes across REPL turns."""

    def __init__(self) -> None:
        self.turns: List[Dict[str, Any]] = []
        self.subgoal_counter: int = 0

    def next_subgoal_id(self) -> str:
        self.subgoal_counter += 1
        return f"sg-repl-{self.subgoal_counter}"

    def add_turn(
        self,
        prompt: str,
        subgoal_id: str,
        plan: Any,
        breakage_report: Any | None,
        repair_outcome: Any | None,
        elapsed_ms: int,
    ) -> None:
        self.turns.append({
            "prompt": prompt,
            "subgoal_id": subgoal_id,
            "plan_id": getattr(plan, "plan_id", None),
            "plan_intent": getattr(plan, "intent", None),
            "target_skill": getattr(plan, "targetskillid", None),
            "segments": getattr(plan, "segments", []),
            "breakages_detected": (
                len(breakage_report.errors) + len(breakage_report.missing_segments)
                if breakage_report and not breakage_report.is_clean
                else 0
            ),
            "repair_applied": (
                repair_outcome.success
                if repair_outcome and hasattr(repair_outcome, "success")
                else None
            ),
            "elapsed_ms": elapsed_ms,
        })

    def clear(self) -> None:
        self.turns.clear()
        self.subgoal_counter = 0

    def summary(self) -> str:
        if not self.turns:
            return "(no turns yet)"
        lines = [f"{len(self.turns)} turn(s):"]
        for i, t in enumerate(self.turns):
            lines.append(
                f"  [{i + 1}] {t['prompt'][:60]}"
                f" => {t['plan_id'] or '?'}"
                f" ({t['elapsed_ms']}ms)"
            )
        return "\n".join(lines)


# ── Pipeline ─────────────────────────────────────────────────────────────────


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run_s2_pipeline(
    prompt: str,
    ctx: ConversationContext,
    governance: MemoryGovernance,
    planner: AgentPlanner,
    repair: PlanRepair,
    plan_memory: PlanMemory,
) -> Dict[str, Any]:
    """Run the full S2 pipeline for a single prompt.

    Steps:  create subgoal → register with governance → generate plan →
            detect breakages → repair if needed.

    Returns a dict with plan, breakage_report, repair_outcome, elapsed_ms.
    """
    t0 = time.perf_counter()

    subgoal_id = ctx.next_subgoal_id()
    subgoal = Subgoal(
        subgoal_id=subgoal_id,
        goal=prompt,
        context={"source": "repl", "turn": len(ctx.turns)},
        metadata={"timestamp": _now_iso()},
        state=SubgoalLifecycleState.CREATED,
        created_at=_now_ms(),
    )
    governance.put_subgoal(subgoal)

    # ── 1. Plan generation ──
    agent_plan = planner.plan(
        subgoal_id=subgoal_id,
        goal=prompt,
        governance=governance,
        timestamp=_now_iso(),
    )

    # ── 2. Convert to memory record for breakage detection ──
    plan_record = PlanMemoryRecord(
        plan_id=agent_plan.plan_id,
        subgoal_id=agent_plan.subgoal_id,
        segments=agent_plan.segments,
        created_at=agent_plan.created_at,
        metadata=agent_plan.metadata,
        intent=agent_plan.intent,
        targetskillid=agent_plan.targetskillid,
        arguments=agent_plan.arguments,
        reasoning_summary=agent_plan.reasoning_summary,
    )

    subgoal_record = SubgoalMemoryRecord(
        subgoal_id=subgoal.subgoal_id,
        parent_id=subgoal.parent_id,
        state=subgoal.state.value,
        goal=subgoal.goal,
        context=subgoal.context,
        metadata=subgoal.metadata,
        created_at=subgoal.created_at,
    )

    # ── 3. Breakage detection ──
    breakage_report = repair.detect_breakages(
        plan_record=plan_record,
        real_segments_by_id={},
        regenerated_ids=set(),
        subgoals_by_id={subgoal_id: subgoal_record},
        drift_events=[],
        now=_now_ms(),
    )

    # ── 4. Repair (if not clean) ──
    repair_outcome = None
    if not breakage_report.is_clean:
        repair_outcome = repair.repair(
            plan_record=plan_record,
            real_segments_by_id={},
            subgoals_by_id={subgoal_id: subgoal_record},
            drift_events=[],
            now=_now_ms(),
            repair_budget=5,
            retry_limit=3,
        )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    ctx.add_turn(prompt, subgoal_id, agent_plan, breakage_report, repair_outcome, elapsed_ms)

    return {
        "plan": agent_plan,
        "breakage_report": breakage_report,
        "repair_outcome": repair_outcome,
        "elapsed_ms": elapsed_ms,
    }


# ── Display helpers ──────────────────────────────────────────────────────────


def _display_plan(agent_plan: Any) -> None:
    print(f"\n  Plan ID   : {agent_plan.plan_id}")
    print(f"  Intent    : {agent_plan.intent}")
    print(f"  Skill     : {agent_plan.targetskillid}")
    print(f"  Reasoning : {agent_plan.reasoning_summary}")
    print(f"  Segments  : {agent_plan.segments}")
    args_str = json.dumps(agent_plan.arguments, indent=2)
    print(f"  Arguments : {args_str}")


def _display_breakages(report: Any) -> None:
    if not report:
        return
    if report.is_clean:
        print("  Breakages : none (plan is clean) [OK]")
        return
    issues = (
        len(report.errors)
        + len(report.missing_segments)
        + len(report.invalid_links)
    )
    print(f"  Breakages : {issues} issue(s) [!]")
    for e in report.errors[:5]:
        print(f"    error  : {e.error_type} on {e.record_id}")
    for ms in report.missing_segments[:5]:
        print(f"    missing: {ms}")
    for il in report.invalid_links[:5]:
        print(f"    link   : {il.link_type} {il.from_id} -> {il.to_id}")


def _display_repair(outcome: Any) -> None:
    if outcome is None:
        print("  Repair    : not needed")
        return
    status = "[OK] success" if outcome.success else "[FAIL] failed"
    print(f"  Repair    : {status}")
    print(f"  Attempts  : {outcome.attempts}, budget used: {outcome.budget_used}")
    acts = outcome.repair_actions_applied
    if acts:
        for a in acts[:5]:
            print(f"    action  : {a.action_type} on {a.target_id}")
    if outcome.errors:
        for e in outcome.errors:
            print(f"    error: {e}")


def _display_result(result: Dict[str, Any]) -> None:
    print(SEP)
    _display_plan(result["plan"])
    _display_breakages(result["breakage_report"])
    _display_repair(result["repair_outcome"])
    print(f"  Time      : {result['elapsed_ms']}ms")
    print(SEP)


# ── REPL ─────────────────────────────────────────────────────────────────────


def repl_loop(
    ctx: ConversationContext,
    governance: MemoryGovernance,
    planner: AgentPlanner,
    repair: PlanRepair,
    plan_memory: PlanMemory,
) -> None:
    """Run the REPL loop until the user quits."""

    print(SEP)
    print("  vai-core S2 REPL Test Harness")
    print("  Type a prompt to plan it.  Type :help for commands.")
    print(SEP)

    while True:
        try:
            line = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n:quit")
            break

        if not line:
            continue

        # ── Commands ──
        if line.startswith(":"):
            cmd = line[1:].lower().split()[0]
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help":
                print(HELP_TEXT)
            elif cmd == "history":
                print(ctx.summary())
            elif cmd == "plans":
                if not ctx.turns:
                    print("(no plans yet)")
                else:
                    for t in ctx.turns:
                        print(f"  {t['plan_id']} ← '{t['prompt'][:50]}'")
            elif cmd == "context":
                print(json.dumps({
                    "turns": len(ctx.turns),
                    "next_subgoal": ctx.next_subgoal_id(),
                }, indent=2))
                # undo the counter bump from displaying context
                ctx.subgoal_counter -= 1
            elif cmd == "clear":
                ctx.clear()
                print("Context cleared.")
            else:
                print(f"Unknown command: :{cmd}.  Type :help for options.")
            continue

        # ── Run pipeline ──
        print(f"\n  Processing: \"{line[:80]}\"")
        try:
            result = run_s2_pipeline(line, ctx, governance, planner, repair, plan_memory)
            _display_result(result)
        except Exception as exc:
            print(f"\n  Error: {exc}")


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="vai-core S2 REPL test harness (Phase 2.18.6)"
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="Use MockLLM (deterministic, default). Use without --mock for real LLM.",
    )
    args = parser.parse_args()

    # ── Build S2 pipeline ──
    sm = SubgoalMemory()
    segm = SegmentMemory()
    pm = PlanMemory()
    dm = DriftMemory()
    governance = MemoryGovernance(sm, segm, pm, dm)

    if args.mock or True:  # default to mock for safety
        planner = AgentPlanner(llm=MockLLM(), plan_memory=pm)
    else:
        from src.core.planning.s1_contract.s1_real_client import ENABLE_REAL_LLM
        ENABLE_REAL_LLM = True  # noqa: F841 — deliberately set
        # Use real LLM-backed ChatProvider
        from src.core.planning.s1_contract.s1_client import call_s1_backend
        raise NotImplementedError("Real LLM backend not yet wired for REPL harness")

    repair = PlanRepair()
    ctx = ConversationContext()

    repl_loop(ctx, governance, planner, repair, pm)

    print(f"\nDone.  {len(ctx.turns)} turn(s) processed.")


if __name__ == "__main__":
    main()
