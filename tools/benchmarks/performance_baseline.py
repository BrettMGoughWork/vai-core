"""
Performance baseline benchmark for Release 0.1 S2 pipeline.

Phase 2.18.3: Measures end-to-end latency for representative plans.
No optimisation — just measurement. Run with:

    python -m tools.benchmarks.performance_baseline [--iterations N]

Outputs SLO baseline numbers for:
- Tₚ : Plan generation latency
- Tₑ : Step execution latency
- Tᵣ : Repair latency
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any, Dict, List, Tuple

from src.strategy.memory.governance.memory_governance import MemoryGovernance
from src.strategy.memory.subgoal_memory import SubgoalMemory
from src.strategy.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.strategy.memory.segment_memory import SegmentMemory
from src.strategy.memory.plan_memory import PlanMemory
from src.strategy.memory.drift_memory import DriftMemory
from src.strategy.memory.drift_memory_types import DriftEvent
from src.strategy.memory.repair.plan_repair import PlanRepair
from src.strategy.memory.plan_memory_types import PlanMemoryRecord
from src.strategy.memory.segment_memory_types import SegmentMemoryRecord
from src.strategy.planning.agent_planner import AgentPlanner
from src.strategy.planning.contracts.agent_plan import CURRENT_CONTRACT_VERSION
from src.strategy.planning.models.plan import Plan

# ── Helpers ────────────────────────────────────────────────────────────────

_NOW = int(time.time() * 1000)
_NOW_ISO = "2025-01-01T00:00:00Z"


def _make_stores() -> Tuple[SubgoalMemory, SegmentMemory, PlanMemory, DriftMemory]:
    return SubgoalMemory(), SegmentMemory(), PlanMemory(), DriftMemory()


def _make_governance(
    sm: SubgoalMemory, segm: SegmentMemory, pm: PlanMemory, dm: DriftMemory
) -> MemoryGovernance:
    return MemoryGovernance(sm, segm, pm, dm)


def _make_planner(pm: PlanMemory) -> AgentPlanner:
    from src.strategy.llm.mock_llm import MockLLM
    return AgentPlanner(llm_complete=MockLLM().make_complete(), plan_memory=pm)


def _make_plan_record() -> PlanMemoryRecord:
    return PlanMemoryRecord(
        plan_id="plan-bench",
        subgoal_id="sg-bench",
        segments=["seg-1", "seg-2"],
        created_at=_NOW_ISO,
        metadata={},
        intent="benchmark task",
        targetskillid="stdlib.echo",
        arguments={},
        reasoning_summary="benchmark",
    )


def _make_segment_record(seg_id: str) -> SegmentMemoryRecord:
    return SegmentMemoryRecord(
        segment_id=seg_id,
        subgoal_id="sg-bench",
        parent_id=None,
        content=["step-1"],
        state=None,
        context={},
        metadata={},
        created_at=_NOW_ISO,
    )


def _make_subgoal_record() -> SubgoalMemoryRecord:
    return SubgoalMemoryRecord(
        subgoal_id="sg-bench",
        parent_id=None,
        state="created",
        goal="benchmark goal",
        context={},
        metadata={},
        created_at=_NOW,
    )


def _make_plan() -> Plan:
    return Plan(
        intent="benchmark task",
        targetskillid="stdlib.echo",
        arguments={"message": "hello"},
        reasoning_summary="benchmark",
    )


# ── Benchmark functions ────────────────────────────────────────────────────

def bench_plan_generation(iterations: int) -> Dict[str, Any]:
    """Measure AgentPlanner.plan() latency."""
    sm, segm, pm, dm = _make_stores()
    governance = _make_governance(sm, segm, pm, dm)
    from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState
    sg = Subgoal(
        subgoal_id="sg-bench",
        goal="benchmark goal",
        context={},
        metadata={},
        state=SubgoalLifecycleState.CREATED,
        created_at=_NOW,
    )
    governance.put_subgoal(sg)
    planner = _make_planner(pm)

    times: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        planner.plan(
            subgoal_id="sg-bench",
            goal="benchmark goal — echo a message",
            governance=governance,
            timestamp=_NOW_ISO,
        )
        t1 = time.perf_counter()
        times.append(t1 - t0)

    return _summarize("plan_generation", times, iterations)


def bench_repair(iterations: int) -> Dict[str, Any]:
    """Measure PlanRepair.repair() latency on a broken plan."""
    repair = PlanRepair()
    plan_record = _make_plan_record()
    segments: dict[str, SegmentMemoryRecord] = {"seg-1": _make_segment_record("seg-1")}
    subgoals: dict[str, SubgoalMemoryRecord] = {"sg-bench": _make_subgoal_record()}

    times: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        repair.repair(
            plan_record=plan_record,
            real_segments_by_id=segments,
            subgoals_by_id=subgoals,
            drift_events=[],
            now=_NOW,
            repair_budget=5,
            retry_limit=3,
        )
        t1 = time.perf_counter()
        times.append(t1 - t0)

    return _summarize("repair", times, iterations)


def bench_breakage_detection(iterations: int) -> Dict[str, Any]:
    """Measure PlanRepair.detect_breakages() latency."""
    repair = PlanRepair()
    plan_record = _make_plan_record()
    segments: dict[str, SegmentMemoryRecord] = {"seg-1": _make_segment_record("seg-1")}
    subgoals: dict[str, SubgoalMemoryRecord] = {"sg-bench": _make_subgoal_record()}

    times: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        repair.detect_breakages(
            plan_record=plan_record,
            real_segments_by_id=segments,
            regenerated_ids=set(),
            subgoals_by_id=subgoals,
            drift_events=[],
            now=_NOW,
        )
        t1 = time.perf_counter()
        times.append(t1 - t0)

    return _summarize("breakage_detection", times, iterations)


def bench_contract_serialization(iterations: int) -> Dict[str, Any]:
    """Measure AgentPlan.to_dict() / from_dict() roundtrip latency."""
    from src.strategy.planning.contracts.agent_plan import AgentPlan

    plan = AgentPlan(
        plan_id="plan-bench",
        subgoal_id="sg-bench",
        segments=["seg-1", "seg-2", "seg-3", "seg-4", "seg-5"],
        intent="benchmark a multi-segment plan with reasoning",
        targetskillid="stdlib.echo",
        arguments={"message": "hello", "recipient": "world"},
        reasoning_summary="chose stdlib.echo because it satisfies the goal",
        created_at=_NOW_ISO,
        metadata={"source": "benchmark", "version": 1},
        subgoals=["sg-bench"],
    )

    times: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        d = plan.to_dict()
        AgentPlan.from_dict(d)
        t1 = time.perf_counter()
        times.append(t1 - t0)

    return _summarize("contract_serialization", times, iterations)


def bench_end_to_end(iterations: int) -> Dict[str, Any]:
    """Measure full plan→detect pipeline latency (mock execution)."""
    repair = PlanRepair()
    sm, segm, pm, dm = _make_stores()
    governance = _make_governance(sm, segm, pm, dm)
    from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState
    sg = Subgoal(
        subgoal_id="sg-bench",
        goal="benchmark goal",
        context={},
        metadata={},
        state=SubgoalLifecycleState.CREATED,
        created_at=_NOW,
    )
    governance.put_subgoal(sg)
    planner = _make_planner(pm)

    times: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()

        agent_plan = planner.plan(
            subgoal_id="sg-bench",
            goal="benchmark goal — echo a message",
            governance=governance,
            timestamp=_NOW_ISO,
        )

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

        repair.detect_breakages(
            plan_record=plan_record,
            real_segments_by_id={},
            regenerated_ids=set(),
            subgoals_by_id={"sg-bench": _make_subgoal_record()},
            drift_events=[],
            now=_NOW,
        )

        t1 = time.perf_counter()
        times.append(t1 - t0)

    return _summarize("end_to_end_plan_detect", times, iterations)


# ── Utilities ───────────────────────────────────────────────────────────────

def _summarize(op: str, times: List[float], n: int) -> Dict[str, Any]:
    return {
        "operation": op,
        "iterations": n,
        "mean_ms": statistics.mean(times) * 1000,
        "median_ms": statistics.median(times) * 1000,
        "p95_ms": _percentile(times, 95) * 1000,
        "p99_ms": _percentile(times, 99) * 1000,
        "min_ms": min(times) * 1000,
        "max_ms": max(times) * 1000,
        "stdev_ms": statistics.stdev(times) * 1000 if len(times) > 1 else 0,
    }


def _percentile(data: List[float], p: float) -> float:
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_data):
        return sorted_data[f] + c * (sorted_data[f + 1] - sorted_data[f])
    return sorted_data[f]


def _format_slo_table(results: List[Dict[str, Any]]) -> str:
    lines = [
        "| Operation | Mean (ms) | P95 (ms) | P99 (ms) | Min (ms) | Max (ms) |",
        "|-----------|-----------|----------|----------|----------|----------|",
    ]
    for r in results:
        lines.append(
            f"| {r['operation']} | {r['mean_ms']:.3f} | "
            f"{r['p95_ms']:.3f} | {r['p99_ms']:.3f} | "
            f"{r['min_ms']:.3f} | {r['max_ms']:.3f} |"
        )
    return "\n".join(lines)


def _suggest_slos(results: List[Dict[str, Any]]) -> str:
    lines = ["\n## Suggested SLOs\n"]
    headroom = 2.0
    for r in results:
        lines.append(
            f"- **{r['operation']}**: < {r['p95_ms'] * headroom:.1f} ms "
            f"(p95={r['p95_ms']:.3f} ms x {headroom:.0f}x headroom)"
        )
    return "\n".join(lines)


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="S2 performance baseline benchmark (Phase 2.18.3)"
    )
    parser.add_argument(
        "--iterations", "-n", type=int, default=100,
        help="Number of iterations per benchmark (default: 100)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    print(f"Running performance baseline ({args.iterations} iterations each)...\n")

    results: List[Dict[str, Any]] = []

    for name, fn in [
        ("plan_generation", bench_plan_generation),
        ("breakage_detection", bench_breakage_detection),
        ("repair", bench_repair),
        ("contract_serialization", bench_contract_serialization),
        ("end_to_end", bench_end_to_end),
    ]:
        print(f"  Benchmarking {name}...", end=" ", flush=True)
        result = fn(args.iterations)
        results.append(result)
        print(f"mean={result['mean_ms']:.3f}ms, p95={result['p95_ms']:.3f}ms")

    print()
    print(_format_slo_table(results))
    print(_suggest_slos(results))

    if args.json:
        print("\n## JSON Output")
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
