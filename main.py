"""
main.py — single-cycle architecture verification for Stratum-2.

Constructs a minimal AgentState (one subgoal, empty memories, default config),
runs exactly ONE agent cycle via AgentLoopV2, then prints three artefacts:

  1. AgentCycleOutcome  — what happened in the cycle
  2. AgentRunTrace      — the full run envelope (one cycle)
  3. Memory Substrate   — snapshot of all four memory stores post-cycle

All output is stable JSON (indent=2, sort_keys=True).
The cycle outcome is also written to agent_traces/ for TUI inspection.

No REPL. No LLM calls. No stdin. No global state.
Exits cleanly with code 0 on success, 1 on unexpected error.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from src.core.memory.drift_memory import DriftMemory
from src.core.memory.plan_memory import PlanMemory
from src.core.memory.segment_memory import SegmentMemory
from src.core.memory.subgoal_memory import SubgoalMemory
from src.core.planning.agent_loop.agent_loop_types import AgentLoopConfig, AgentState
from src.core.planning.agent_loop.agent_loop_v2 import AgentLoopV2
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState


# ---------------------------------------------------------------------------
# JSON serialisation
# ---------------------------------------------------------------------------

def _json_default(obj):
    """Fallback encoder for types not handled by stdlib json."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (set, frozenset)):
        return sorted(str(x) for x in obj)
    return str(obj)


def _dump(label: str, data: dict) -> None:
    sep = "=" * 64
    print(f"\n{sep}")
    print(f"  {label}")
    print(sep)
    print(json.dumps(data, indent=2, sort_keys=True, default=_json_default))


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # ── 1. Construct minimal AgentState ─────────────────────────────────────
    #
    # One subgoal in CREATED state (start of the execution lifecycle).
    # All other memory stores are empty.
    # Default AgentLoopConfig (budgets, limits).
    subgoal = Subgoal.new(
        goal="Verify Stratum-2 AgentLoopV2 architecture",
        context={"source": "main.py", "run": "smoke-test"},
        metadata={"phase": "2.5.6"},
    )
    # Advance from default PENDING to CREATED so it enters the active lifecycle.
    # This is initial state construction — not a governed runtime transition.
    subgoal = subgoal.with_state(SubgoalLifecycleState.CREATED)

    subgoal_memory = SubgoalMemory()
    subgoal_memory.put(subgoal)

    state = AgentState(
        subgoal_memory=subgoal_memory,
        segment_memory=SegmentMemory(),
        plan_memory=PlanMemory(),
        drift_memory=DriftMemory(),
        config=AgentLoopConfig(),
    )

    # ── 2. Run exactly one agent cycle ──────────────────────────────────────
    loop = AgentLoopV2()
    trace = loop.run_agent_loop(state, max_cycles=1)

    if not trace.cycles:
        print("[error] run_agent_loop returned no cycles — unexpected.", file=sys.stderr)
        sys.exit(1)

    cycle_outcome = trace.cycles[0]
    memory_snapshot = state.to_snapshot(_now_iso())

    # ── 3. Print the three artefacts ────────────────────────────────────────
    _dump("1. AgentCycleOutcome", asdict(cycle_outcome))
    _dump("2. AgentRunTrace",     asdict(trace))
    _dump("3. Memory Substrate",  asdict(memory_snapshot))

    # ── 4. Write cycle trace to agent_traces/ for TUI inspection ────────────
    trace_dir = Path("agent_traces")
    trace_dir.mkdir(exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S")
    trace_file = trace_dir / f"cycle_{cycle_outcome.cycle:04}_{ts}.json"
    trace_file.write_text(
        json.dumps(asdict(cycle_outcome), indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )

    print(f"\n[trace] written to {trace_file}")
    print(
        f"[summary] cycle={cycle_outcome.cycle}  "
        f"terminal={cycle_outcome.terminal}  "
        f"reason={cycle_outcome.termination_reason}  "
        f"errors={len(cycle_outcome.errors)}"
    )

    sys.exit(0)


if __name__ == "__main__":
    main()
