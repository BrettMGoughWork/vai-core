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


def load_all_skills(skill_registry, prim_registry, embedder=None) -> int:
    """Load all .skill.md files from stdlib into the CapabilitySkillRegistry.

    Delegates to the canonical loader in ``src.capabilities.skills.stdlib``.

    **PHASE 3.19.2**: If *embedder* is provided, it is set on the registry
    before loading so that every skill receives a pre‑computed embedding at
    registration time.  The embedding is stored on ``CapabilitySkill.embedding``
    and in the vector store.

    Returns the count of loaded skills.
    """
    from src.capabilities.skills.stdlib import load_all_skills as _load

    return _load(skill_registry, prim_registry, embedder=embedder)


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

        # Wire up external primitive loaders (CLI, MCP) — ready when config provided
        from src.capabilities.registry.loaders import load_external_loaders

        prim_count += load_external_loaders(prim_registry)

        _out(f"{MINOR} PRIMITIVES {MINOR}")
        _out(f"  Loaded: {prim_count} primitives")

        # ── 2. Wire up SkillRegistry ─────────────────────────────────────
        from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
        from src.capabilities.discovery.embedder import SkillEmbedder
        from src.capabilities.discovery.providers.mock_provider import MockEmbeddingProvider
        from src.capabilities.discovery.providers.local_provider import LocalEmbeddingProvider

        # Use real embeddings for real_llm, mock for mock tests
        if backend == "real_llm":
            provider = LocalEmbeddingProvider(model="all-MiniLM-L6-v2", dimensions=384)
        else:
            provider = MockEmbeddingProvider(dimensions=8)
        embedder = SkillEmbedder(provider=provider)
        skill_registry = CapabilitySkillRegistry(embedder=embedder)
        skill_count = load_all_skills(skill_registry, prim_registry, embedder=embedder)
        _out(f"  Loaded: {skill_count} skills")

        # ── 3. Wire up SkillRunner → S3Adapter ───────────────────────────
        from src.capabilities.runtime.skill_runner import SkillRunner
        from src.strategy.planning.adapters.s3_adapter import S3Adapter

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
        s3_adapter = S3Adapter(runner)

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
            from src.strategy.llm.mock_llm import MockLLM
            llm = MockLLM()
            model = "mock"
        else:
            from src.strategy.llm.llm_factory import factory
            provider = os.environ.get("LLM_PROVIDER", "deepseek")
            model = os.environ.get("LLM_MODEL", "deepseek-chat")
            llm = factory.create(provider, model)

        # ── 6. Wire up SubgoalPlanner ────────────────────────────────────
        from src.strategy.planning.generator.subgoal_planner import SubgoalPlanner
        planner = SubgoalPlanner(llm=llm, model=model, s3_adapter=s3_adapter)

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

        # ── 9. Execute plan steps via S3Adapter ──────────────────────────
        _out(f"\n{MINOR} SKILL EXECUTION {MINOR}")

        from src.strategy.planning.adapters.s3_adapter import S2SkillCallRequest

        # Build runtime context with search config for primitives (PHASE 3.13.2)
        runtime_context: dict = {}
        try:
            from src.strategy.config.loader import Config
            cfg = Config("config/config.yaml")
            search_cfg = cfg.get("search")
            if search_cfg is not None and search_cfg.enabled:
                runtime_context["search_config"] = search_cfg
        except Exception:
            pass  # config not available — primitives use their defaults

        accumulated_outputs: dict[str, Any] = {}

        # Simple template resolver for forward-reference resolution
        _STEP_REF_RE = re.compile(r"^step-\d+$")

        def _resolve_templates(value: Any, sources: dict[str, Any], parent_key: str = "") -> Any:
            """Resolve '{{key}}' tokens, fallback '{{step-N}}' references, and
            legacy '$ref' / JSONPath-like strings against *sources* (accumulated
            outputs from previous steps)."""
            if isinstance(value, str):
                # 1. Bare {{key}} token → return raw source value
                m = re.match(r"^\{\{\s*([\w-]+)\s*\}\}$", value)
                if m:
                    key = m.group(1)
                    if key in sources:
                        return sources[key]
                    # Fallback: {{step-N}} → stringified accumulated outputs
                    if _STEP_REF_RE.match(key):
                        return json.dumps(sources, default=str)
                    return value
                # 2. Embedded {{key}} tokens → stringify
                def _replacer(m: re.Match[str]) -> str:
                    key = m.group(1)
                    if key in sources:
                        return str(sources[key])
                    if _STEP_REF_RE.match(key):
                        return json.dumps(sources, default=str)
                    return m.group(0)
                value = re.sub(
                    r"\{\{\s*([\w-]+)\s*\}\}",
                    _replacer,
                    value,
                )
                # 3. JSONPath-like reference (e.g., "$.steps[0].result", "$.steps[0].output")
                #    If the parent_key exists in sources, return its value
                if value.startswith("$.") and parent_key and parent_key in sources:
                    return sources[parent_key]
                return value
            if isinstance(value, dict):
                # Handle $ref references to previous step outputs
                ref = value.get("$ref")
                if ref is not None and isinstance(ref, str) and len(value) == 1:
                    if parent_key and parent_key in sources:
                        return sources[parent_key]
                    return sources
                return {k: _resolve_templates(v, sources, parent_key=k) for k, v in value.items()}
            if isinstance(value, list):
                return [_resolve_templates(v, sources) for v in value]
            return value

        for i, step in enumerate(result.plan_steps):
            skill_name = result.target_skill if i == 0 else step.get("capability", result.target_skill)
            description = step.get("description", f"step-{i}")
            # Per-step inputs take precedence; fall back to plan-level arguments
            raw_inputs = step.get("inputs") or plan_record.arguments or {}
            # Resolve forward-references to previous step outputs
            if i > 0 and accumulated_outputs:
                raw_inputs = _resolve_templates(raw_inputs, accumulated_outputs)
            # Merge previous outputs as defaults (step inputs override via template resolution)
            step_inputs = {**accumulated_outputs, **raw_inputs}

            _out(f"\n  [{i+1}/{len(result.plan_steps)}] {description}")
            _out(f"       skill: {skill_name}")

            s2_request = S2SkillCallRequest(
                skill_name=skill_name,
                arguments=step_inputs,
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
                    if s2_result.output and isinstance(s2_result.output, dict):
                        accumulated_outputs.update(s2_result.output)
                        # Store per-step output for {{step-N}} fallback references
                        accumulated_outputs[f"step-{i+1}"] = json.dumps(s2_result.output, default=str)
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
