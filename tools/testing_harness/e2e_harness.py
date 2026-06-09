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
import math
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


def _simple_embedding_fn(text: str) -> list[float]:
    """Deterministic embedding: character-bucket hash, unit-normalised."""
    vec = [0.0] * 8
    for ch in text:
        idx = ord(ch) % 8
        vec[idx] += 1.0
    magnitude = math.sqrt(sum(v * v for v in vec))
    if magnitude > 0:
        vec = [v / magnitude for v in vec]
    return vec


# ══════════════════════════════════════════════════════════════════════════════
# Primitive auto-discovery
# ══════════════════════════════════════════════════════════════════════════════


def load_all_primitives(registry) -> int:
    """Auto-discover all stdlib primitives and register them.

    Scans ``src/capabilities/primitives/stdlib/`` for ``*Primitive`` classes,
    imports each, instantiates it, and registers it by its ``.name`` attribute.

    Returns the count of registered primitives.
    """
    from src.capabilities.primitives.base import PrimitiveBase

    stdlib_dir = _PROJECT_ROOT / "src" / "capabilities" / "primitives" / "stdlib"
    count = 0

    for py_file in sorted(stdlib_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module_path = f"src.capabilities.primitives.stdlib.{py_file.stem}"

        try:
            module = importlib.import_module(module_path)
        except Exception as exc:
            print(f"  ⚠ Failed to import {module_path}: {exc}", file=sys.stderr)
            continue

        for attr_name in dir(module):
            if not attr_name.endswith("Primitive"):
                continue
            cls = getattr(module, attr_name)
            if not isinstance(cls, type) or not issubclass(cls, PrimitiveBase):
                continue
            if cls is PrimitiveBase:
                continue

            try:
                instance = cls()
                registry.register(instance.name, instance)
                count += 1
            except Exception as exc:
                print(f"  ⚠ Failed to register {cls.__name__}: {exc}", file=sys.stderr)
                continue

    return count


# ══════════════════════════════════════════════════════════════════════════════
# Skill loading
# ══════════════════════════════════════════════════════════════════════════════


def _extract_yaml_frontmatter(text: str, source: str) -> dict[str, Any]:
    """Extract YAML between ``---`` delimiters from a .skill.md file."""
    import yaml

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Missing opening --- in {source}")

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        raise ValueError(f"Missing closing --- in {source}")

    yaml_text = "\n".join(lines[1:end_idx])
    return yaml.safe_load(yaml_text)


def load_all_skills(skill_registry, prim_registry) -> int:
    """Load all .skill.md files from stdlib into the CapabilitySkillRegistry.

    Uses ``SkillManifest.from_dict()`` to parse the raw YAML frontmatter
    into a validated manifest, then ``CapabilitySkill.from_manifest()`` to
    resolve primitives and build the runtime skill.

    Returns the count of loaded skills.
    """
    from src.capabilities.skills.manifest import SkillManifest
    from src.capabilities.skills.skill import CapabilitySkill

    skills_dir = _PROJECT_ROOT / "src" / "capabilities" / "skills" / "stdlib"
    count = 0

    for skill_file in sorted(skills_dir.glob("*.skill.md")):
        try:
            raw_text = skill_file.read_text(encoding="utf-8")
            data = _extract_yaml_frontmatter(raw_text, str(skill_file))

            manifest = SkillManifest.from_dict(data)
            skill = CapabilitySkill.from_manifest(manifest, prim_registry)
            skill_registry.register(skill)
            count += 1
        except Exception as exc:
            print(f"  ⚠ Failed to load {skill_file.name}: {exc}", file=sys.stderr)
            continue

    return count


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

        # ── 2. Wire up SkillRegistry ─────────────────────────────────────
        from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
        skill_registry = CapabilitySkillRegistry()
        skill_count = load_all_skills(skill_registry, prim_registry)
        _out(f"  Loaded: {skill_count} skills")

        # ── 3. Wire up SkillRunner → S3Adapter ───────────────────────────
        from src.capabilities.runtime.skill_runner import SkillRunner
        from src.stratum2.s3_adapter import S3Adapter
        runner = SkillRunner(registry=skill_registry, embedding_fn=_simple_embedding_fn)
        s3_adapter = S3Adapter(runner)

        # ── 4. Wire up MemoryGovernance ──────────────────────────────────
        from src.core.memory.segment_memory import SegmentMemory
        from src.core.memory.subgoal_memory import SubgoalMemory
        from src.core.memory.plan_memory import PlanMemory
        from src.core.memory.drift_memory import DriftMemory
        from src.core.memory.governance.memory_governance import MemoryGovernance

        segment_memory = SegmentMemory()
        subgoal_memory = SubgoalMemory()
        plan_memory = PlanMemory()
        drift_memory = DriftMemory()
        governance = MemoryGovernance(
            subgoal_memory, segment_memory, plan_memory, drift_memory,
        )

        # ── 5. Wire up LLM ───────────────────────────────────────────────
        if backend == "mock":
            from src.core.llm.mock_llm import MockLLM
            llm = MockLLM()
            model = "mock"
        else:
            from src.core.llm.llm_factory import factory
            provider = os.environ.get("LLM_PROVIDER", "deepseek")
            model = os.environ.get("LLM_MODEL", "deepseek-chat")
            llm = factory.create(provider, model)

        # ── 6. Wire up SubgoalPlanner ────────────────────────────────────
        from src.core.planning.generator.subgoal_planner import SubgoalPlanner
        planner = SubgoalPlanner(llm=llm, model=model, s3_adapter=s3_adapter)

        # ── 7. Register subgoal + generate plan ──────────────────────────
        from src.core.types.subgoal import Subgoal, SubgoalLifecycleState
        from src.core.types.hashing import stable_hash

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
                result.plan_steps = [
                    {"id": sid, "description": desc}
                    for sid, desc in zip(
                        seg.context.get("step_ids", []),
                        seg.steps,
                    )
                ]

        _out(f"  Plan ID:     {plan_id[:32]}...")
        _out(f"  Intent:      {result.plan_intent}")
        _out(f"  Target skill:{result.target_skill}")
        _out(f"  Discovered:  {result.discovered_skills}")
        _out(f"  Steps:       {len(result.plan_steps)}")

        # ── 9. Execute plan steps via S3Adapter ──────────────────────────
        _out(f"\n{MINOR} SKILL EXECUTION {MINOR}")

        from src.stratum2.s3_adapter import S2SkillCallRequest

        # Build runtime context with search config for primitives (PHASE 3.13.2)
        runtime_context: dict = {}
        try:
            from src.core.config.loader import Config
            cfg = Config("config/config.yaml")
            search_cfg = cfg.get("search")
            if search_cfg is not None and search_cfg.enabled:
                runtime_context["search_config"] = search_cfg
        except Exception:
            pass  # config not available — primitives use their defaults

        for i, step in enumerate(result.plan_steps):
            skill_name = result.target_skill if i == 0 else step.get("capability", result.target_skill)
            description = step.get("description", f"step-{i}")

            _out(f"\n  [{i+1}/{len(result.plan_steps)}] {description}")
            _out(f"       skill: {skill_name}")

            s2_request = S2SkillCallRequest(
                skill_name=skill_name,
                arguments=plan_record.arguments if i == 0 else {},
                request_id=f"e2e-{plan_id[:8]}-step-{i}",
                context=runtime_context,
            )

            try:
                s2_result = s3_adapter.call_skill(s2_request)
                exec_entry = {
                    "step_index": i,
                    "description": description,
                    "skill_name": skill_name,
                    "success": s2_result.success,
                    "output": s2_result.output,
                    "error": s2_result.error,
                }
                result.execution_results.append(exec_entry)

                if s2_result.success:
                    _out(f"       [OK] success  output={json.dumps(s2_result.output, default=str)[:120]}")
                else:
                    _out(f"       [FAIL] error={s2_result.error}")
            except Exception as exc:
                exec_entry = {
                    "step_index": i,
                    "description": description,
                    "skill_name": skill_name,
                    "success": False,
                    "output": None,
                    "error": str(exc),
                }
                result.execution_results.append(exec_entry)
                _out(f"       [EXCEPTION] {exc}")

        # ── 10. Determine overall success ────────────────────────────────
        result.success = all(
            r["success"] for r in result.execution_results
        ) if result.execution_results else bool(result.plan_id)

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
