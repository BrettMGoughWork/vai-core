"""
repl_harness.py — REPL test harness for the Release 0.1 S2 pipeline (2.18.6)
===========================================================================

A stdin loop that accepts user prompts, runs the full S2 pipeline
(plan → validate → repair → execute), and remembers conversation
context across turns.

Two-part output:
  1. Plan creation & diagnostics (unchanged)
  2. Skill execution results (each step, output on success, error on failure)

This is the primary manual testing interface for Release 0.1→1.0.

Usage:
    python -m tools.testing_harness.repl_harness
    python -m tools.testing_harness.repl_harness --mock       # deterministic, no LLM
    python -m tools.testing_harness.repl_harness --no-execute # plan-only, skip execution

Commands (type at the `s2>` prompt):
    <any text>     — plan it, validate, repair, then execute
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

from src.capabilities.primitives.stdlib import load_all_primitives
from src.capabilities.skills.stdlib import load_all_skills

from src.strategy.memory.governance.memory_governance import MemoryGovernance
from src.strategy.memory.subgoal_memory import SubgoalMemory
from src.strategy.memory.segment_memory import SegmentMemory
from src.strategy.memory.plan_memory import PlanMemory
from src.strategy.memory.drift_memory import DriftMemory
from src.strategy.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.strategy.memory.segment_memory_types import SegmentMemoryRecord
from src.strategy.memory.plan_memory_types import PlanMemoryRecord
from src.strategy.memory.drift_memory_types import DriftEvent
from src.strategy.memory.repair.plan_repair import PlanRepair
from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState
from src.strategy.planning.agent_planner import AgentPlanner
from src.strategy.planning.models.plan import Plan
from src.capabilities.contracts import SkillCallRequest, DiscoveryQuery
from src.capabilities.runtime.skill_runner import SkillRunner


# ── Constants ────────────────────────────────────────────────────────────────

SEP = "=" * 72
PROMPT = "s2> "
HELP_TEXT = """
Commands:
  <any text>     — plan → validate → repair → execute
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

    def build_conversation_prefix(self) -> str:
        """Build conversation history text to prepend to the LLM prompt.

        Reuses existing turn data (prompts + execution outputs) so the
        planner can see what was said and done in prior turns.  This
        keeps the S2 planner interface unchanged — history is embedded
        directly in the goal string passed to plan_for_subgoal.
        """
        if not self.turns:
            return ""

        parts = ["Previous conversation:", ""]
        for i, t in enumerate(self.turns):
            parts.append(f"  User: {t['prompt']}")
            # Extract the assistant's textual response from execution output
            exec_data = t.get("execution")
            if exec_data and isinstance(exec_data, dict) and exec_data.get("steps"):
                outputs = []
                for step in exec_data["steps"]:
                    skill_name = step.get("skill", "?")
                    if step.get("ok") and step.get("output"):
                        try:
                            res = json.loads(step["output"])
                            if isinstance(res, dict):
                                # Pick the first non-empty string value
                                for v in res.values():
                                    if isinstance(v, str) and v.strip():
                                        outputs.append(v)
                                        break
                        except (json.JSONDecodeError, TypeError):
                            outputs.append(step["output"])
                    elif step.get("error"):
                        outputs.append(f"(error: {step['error']})")
                if outputs:
                    parts.append(f"  Assistant: {outputs[0]}")
            else:
                parts.append(f"  Assistant: (executed plan {t.get('plan_id', '?')}: {t.get('plan_intent', '?')})")
            parts.append("")
        return "\n".join(parts)

    def summary(self) -> str:
        if not self.turns:
            return "(no turns yet)"
        lines = [f"{len(self.turns)} turn(s):"]
        for i, t in enumerate(self.turns):
            plan_id = t.get('plan_id') or '?'
            intent = t.get('plan_intent') or ''
            skill = t.get('target_skill') or ''
            lines.append(f"  [{i + 1}] {t['prompt'][:60]}")
            lines.append(f"       plan={plan_id} intent='{intent}' skill={skill}")
            exec_data = t.get("execution")
            if exec_data and isinstance(exec_data, dict) and exec_data.get("steps"):
                for step in exec_data["steps"]:
                    status = "OK" if step.get("ok") else "FAIL"
                    skill_name = step.get("skill", "?")
                    if step.get("output"):
                        try:
                            res = json.loads(step["output"])
                            if isinstance(res, dict):
                                for v in res.values():
                                    if isinstance(v, str) and v.strip():
                                        lines.append(f"       [{status}] {skill_name}: {v[:80]}")
                                        break
                        except (json.JSONDecodeError, TypeError):
                            lines.append(f"       [{status}] {skill_name}: {step['output'][:80]}")
                    elif step.get("error"):
                        lines.append(f"       [{status}] {skill_name}: {step['error'][:80]}")
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
    skill_refs: list[str] | None = None,
) -> Dict[str, Any]:
    """Run the full S2 pipeline for a single prompt.

    Steps:  create subgoal → register with governance → generate plan →
            detect breakages → repair if needed.

    Returns a dict with plan, breakage_report, repair_outcome, elapsed_ms.
    """
    t0 = time.perf_counter()

    subgoal_id = ctx.next_subgoal_id()

    # ── Build conversation-rich goal ──
    history = ctx.build_conversation_prefix()
    goal = f"{history}\n  Current request: {prompt}" if history else prompt

    subgoal = Subgoal(
        subgoal_id=subgoal_id,
        goal=goal,
        context={"source": "repl", "turn": len(ctx.turns)},
        metadata={"timestamp": _now_iso()},
        state=SubgoalLifecycleState.CREATED,
        created_at=_now_ms(),
    )
    governance.put_subgoal(subgoal)

    # ── 1. Plan generation ──
    agent_plan = planner.plan(
        subgoal_id=subgoal_id,
        goal=goal,
        governance=governance,
        timestamp=_now_iso(),
        skill_refs=skill_refs,
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

    # ── 3. Look up actual segments from governance ──
    real_segments_by_id: dict = {}
    segm_snapshot = governance._segment_memory.snapshot() if hasattr(governance, '_segment_memory') else None
    if segm_snapshot:
        for rec in segm_snapshot.records:
            real_segments_by_id[rec.segment_id] = rec

    # ── 4. Breakage detection ──
    breakage_report = repair.detect_breakages(
        plan_record=plan_record,
        real_segments_by_id=real_segments_by_id,
        regenerated_ids=set(),
        subgoals_by_id={subgoal_id: subgoal_record},
        drift_events=[],
        now=_now_ms(),
    )

    # ── 5. Repair (if not clean) ──
    repair_outcome = None
    if not breakage_report.is_clean:
        repair_outcome = repair.repair(
            plan_record=plan_record,
            real_segments_by_id=real_segments_by_id,
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


def _display_flow_header(user_prompt: str) -> None:
    """Display a pipeline flow header showing the S2→S3 chain."""
    print(SEP)
    print("  PIPELINE  Prompt → LLM → Planner → Skills → Execute")
    print(SEP)


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
    """Display plan creation results with pipeline flow visualization."""
    agent_plan = result["plan"]
    # ── Part 1 Header: Pipeline flow ──
    print(f"\n  {SEP}")
    print(f"  PIPELINE  Prompt → LLM → Planner → Skill → Execute")
    print(f"  {SEP}")
    print(f"\n  ── PHASE 1: Plan Creation ──")
    _display_plan(agent_plan)
    _display_breakages(result["breakage_report"])
    _display_repair(result["repair_outcome"])
    print(f"  Time      : {result['elapsed_ms']}ms")
    print(f"  {SEP}")


# ── Plan execution (Part 2) ──────────────────────────────────────────────────


def _execute_plan_steps(
    plan_id: str,
    plan_memory: PlanMemory,
    governance: MemoryGovernance,
    runner: SkillRunner,
    user_prompt: str = "",
) -> Dict[str, Any]:
    """Execute the steps of a generated plan via SkillRunner.

    Returns a dict with success, steps, outputs, errors, elapsed_ms.
    """
    import re as _re

    t0 = time.perf_counter()
    result: Dict[str, Any] = {
        "success": False,
        "steps": [],
        "outputs": [],
        "errors": [],
        "elapsed_ms": 0,
    }

    plan_record = plan_memory.get_record(plan_id)
    if plan_record is None:
        result["errors"].append("Plan record not found")
        return result

    # ── Extract segment steps ──
    segment_ids = plan_memory.get_segments(plan_id)
    if not segment_ids:
        # No segments — try executing the plan itself as a single skill call
        if plan_record.targetskillid:
            result["steps"].append({
                "description": plan_record.intent or plan_record.targetskillid,
                "skill": plan_record.targetskillid,
                "inputs": plan_record.arguments or {},
            })
        else:
            result["errors"].append("No segments and no target skill in plan")
            return result
    else:
        for seg_id in segment_ids:
            seg = governance.get_segment(seg_id)
            if seg is None:
                result["errors"].append(f"Segment {seg_id[:16]}... not found")
                continue
            step_ids = seg.context.get("step_ids", [])
            capabilities = seg.context.get("capabilities", [])
            step_inputs_list = seg.context.get("step_inputs", [])
            for i, step_desc in enumerate(seg.steps):
                result["steps"].append({
                    "description": step_desc,
                    "skill": capabilities[i] if i < len(capabilities) else plan_record.targetskillid,
                    "inputs": step_inputs_list[i] if i < len(step_inputs_list) else {},
                    "step_id": step_ids[i] if i < len(step_ids) else f"step-{i}",
                })

    # ── Execute each step ──
    accumulated: Dict[str, Any] = {}
    for i, step in enumerate(result["steps"]):
        skill_name = step.get("skill", plan_record.targetskillid)
        # Per-step inputs take precedence; fall back to plan-level arguments; then user prompt
        raw_inputs = step.get("inputs") or plan_record.arguments or {}
        if not raw_inputs and user_prompt:
            raw_inputs = {
                "prompt": user_prompt,
                "data": user_prompt,
                "text": user_prompt,
                "content": user_prompt,
                "input": user_prompt,
                "query": user_prompt,
                "message": user_prompt,
            }

        # Resolve {{key}} forward-references from previous step outputs
        if i > 0 and accumulated:
            raw_inputs = _resolve_step_templates(raw_inputs, accumulated)

        step_inputs = {**accumulated, **raw_inputs}

        call_request = SkillCallRequest(
            skill_name=skill_name,
            arguments=step_inputs,
        )

        step_result: Dict[str, Any] = {
            "index": i,
            "description": step.get("description", f"step-{i}"),
            "skill": skill_name,
            "success": False,
            "output": None,
            "error": None,
        }

        try:
            s_result = runner.execute(call_request)
            step_result["success"] = s_result.success
            step_result["output"] = s_result.output
            step_result["error"] = s_result.error
            if s_result.success and isinstance(s_result.output, dict):
                accumulated.update(s_result.output)
                # Store per-step output for {{step-N}} fallback references
                accumulated[f"step-{i+1}"] = json.dumps(s_result.output, default=str)
        except Exception as exc:
            step_result["error"] = str(exc)

        result["outputs"].append(step_result)

    result["success"] = all(r["success"] for r in result["outputs"]) if result["outputs"] else False
    result["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return result


_STEP_REF_RE = re.compile(r"^step-\d+$")

def _resolve_step_templates(value: Any, sources: Dict[str, Any]) -> Any:
    """Resolve '{{key}}' tokens in *value* against *sources*.

    Supports:
      - ``{{output_key}}`` → raw value from prior step outputs
      - ``{{step-N}}`` → JSON-stringified accumulated outputs (fallback)
    """
    import re as _re

    if isinstance(value, str):
        m = _re.match(r"^\{\{\s*([\w-]+)\s*\}\}$", value)
        if m:
            key = m.group(1)
            if key in sources:
                return sources[key]
            # Fallback: {{step-N}} → stringified accumulated outputs
            if _STEP_REF_RE.match(key):
                return json.dumps(sources, default=str)
            return value
        return _re.sub(
            r"\{\{\s*([\w-]+)\s*\}\}",
            lambda m: (
                str(sources[m.group(1)]) if m.group(1) in sources
                else json.dumps(sources, default=str) if _STEP_REF_RE.match(m.group(1))
                else m.group(0)
            ),
            value,
        )
    if isinstance(value, dict):
        return {k: _resolve_step_templates(v, sources) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_step_templates(v, sources) for v in value]
    return value


def _display_execution(exec_result: Dict[str, Any]) -> None:
    """Display skill execution results — PHASE 2 of the pipeline."""
    print(f"  ── PHASE 2: Skill Execution ──")
    print(SEP)
    print("  EXECUTION RESULTS")
    print(SEP)
    if exec_result["errors"]:
        for e in exec_result["errors"]:
            print(f"  [ERROR] {e}")
    if not exec_result["outputs"]:
        print("  (no steps executed)")
    else:
        for r in exec_result["outputs"]:
            status = "[OK]" if r["success"] else "[FAIL]"
            desc = r.get("description", "")[:80]
            skill = r.get("skill", "?")
            print(f"  {status} [{skill}] {desc}")
            if r["output"] is not None:
                output_str = json.dumps(r["output"], default=str)
                if len(output_str) > 200:
                    output_str = output_str[:200] + "..."
                print(f"       output: {output_str}")
            if r["error"]:
                print(f"       error: {r['error']}")
    status = "[OK] ALL STEPS PASSED" if exec_result["success"] else "[!] SOME STEPS FAILED"
    print(f"\n  {status}")
    print(f"  Execution time: {exec_result['elapsed_ms']}ms")
    print(SEP)


# ── REPL ─────────────────────────────────────────────────────────────────────


def repl_loop(
    ctx: ConversationContext,
    governance: MemoryGovernance,
    planner: AgentPlanner,
    repair: PlanRepair,
    plan_memory: PlanMemory,
    runner: SkillRunner | None = None,
    execute: bool = True,
) -> None:
    """Run the REPL loop until the user quits.

    Args:
        execute: If False, skip skill execution (plan-only mode).
    """

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
                    "history": ctx.build_conversation_prefix() or "(no history)",
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
            # Discover relevant skills for this prompt
            skill_refs: list[str] | None = None
            if runner is not None:
                discovered = runner.discover(DiscoveryQuery(query=line, limit=5))
                skill_refs = [sk.name for sk in discovered.skills]

            result = run_s2_pipeline(line, ctx, governance, planner, repair, plan_memory, skill_refs)
            _display_result(result)

            # ── Part 2: Execute the plan ──
            if execute and runner is not None:
                plan_id = result["plan"].plan_id
                exec_result = _execute_plan_steps(
                    plan_id, plan_memory, governance, runner, line,
                )
                _display_execution(exec_result)
                # Store execution result in turn history
                if ctx.turns:
                    ctx.turns[-1]["execution"] = exec_result
            elif not execute:
                print("  (execution skipped via --no-execute)")
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
        help="Use MockLLM (deterministic). Use without --mock for real LLM.",
    )
    parser.add_argument(
        "--no-execute", action="store_true",
        help="Skip skill execution — plan + validate + repair only.",
    )
    args = parser.parse_args()

    # ── Build S2 pipeline ──
    sm = SubgoalMemory()
    segm = SegmentMemory()
    pm = PlanMemory()
    dm = DriftMemory()
    governance = MemoryGovernance(sm, segm, pm, dm)

    if args.mock:
        from src.runtime.llm.mock_llm import MockLLM
        llm = MockLLM()
        model = "mock"
    else:
        from src.runtime.llm.llm_factory import factory
        provider = os.environ.get("LLM_PROVIDER", "deepseek")
        model = os.environ.get("LLM_MODEL", "deepseek-chat")
        llm = factory.create(provider, model)

    # ── Wire up skill execution (PrimitiveRegistry → SkillRegistry → SkillRunner) ──
    runner: SkillRunner | None = None
    if not args.no_execute:
        from src.capabilities.registry.primitive_registry import PrimitiveRegistry
        from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
        from src.capabilities.discovery.embedder import SkillEmbedder
        from src.capabilities.discovery.providers.local_provider import LocalEmbeddingProvider
        from src.capabilities.discovery.providers.mock_provider import MockEmbeddingProvider

        # Use real embeddings for real LLM, mock for mock
        if args.mock:
            provider = MockEmbeddingProvider(dimensions=8)
        else:
            provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2", dimensions=384)
        embedder = SkillEmbedder(provider=provider)

        prim_registry = PrimitiveRegistry()
        load_all_primitives(prim_registry)

        skill_registry = CapabilitySkillRegistry(embedder=embedder)
        load_all_skills(skill_registry, prim_registry, embedder)

        # ── Wire up SkillAuthor pipeline (3.17.5 capability discovery) ──
        from src.capabilities.registry.skill_safety import SkillSafetyValidator
        from src.capabilities.skills.author import SkillAuthor
        from src.capabilities.primitives.stdlib.skill_author import set_author_pipeline

        safety_validator = SkillSafetyValidator(
            primitive_registry=prim_registry,
            skill_registry=skill_registry,
        )
        author = SkillAuthor(
            primitive_registry=prim_registry,
            skill_registry=skill_registry,
            safety_validator=safety_validator,
        )
        set_author_pipeline(author)

        runner = SkillRunner(registry=skill_registry, embedder=embedder)

    def _llm_complete(sys_prompt: str, user_msg: str) -> str:
        raw = llm.chat(model=model, messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ])
        return raw["choices"][0]["message"]["content"]

    planner = AgentPlanner(llm_complete=_llm_complete, plan_memory=pm)

    repair = PlanRepair()
    ctx = ConversationContext()

    repl_loop(ctx, governance, planner, repair, pm, runner=runner, execute=not args.no_execute)

    print(f"\nDone.  {len(ctx.turns)} turn(s) processed.")


if __name__ == "__main__":
    main()
