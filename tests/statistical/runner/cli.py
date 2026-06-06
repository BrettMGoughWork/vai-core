"""
cli.py — Manual entry point for the statistical conformance runner.

Not part of pytest.  Manually executed:

    python -m tests.statistical.cli --scenario tiny_plan1 --repetitions 100

Or:

    python -m tests.statistical.cli --scenario tiny_plan1 --repetitions 10 --backend real_llm --verbose
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.statistical.runner.scenario import ConformanceScenario, load_scenario
from tests.statistical.runner.runner import run_scenario
from tests.statistical.runner.thresholds import Thresholds


# ── Scenario lookup ─────────────────────────────────────────────────────────

def _resolve_scenario_path(name: str) -> Path:
    """Resolve a shorthand scenario name to its JSON file path."""
    scenarios_dir = Path(__file__).resolve().parent.parent / "scenarios"

    # Allow both "tiny_plan1" and "tiny_plan1.json"
    if not name.endswith(".json"):
        name = f"{name}.json"

    path = scenarios_dir / name
    if not path.exists():
        print(f"Scenario not found: {path}")
        print(f"Available scenarios:")
        for f in sorted(scenarios_dir.glob("*.json")):
            print(f"  {f.stem}")
        sys.exit(1)
    return path


# ── CLI argument parsing ─────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Statistical Conformance Runner — reusable probabilistic test harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.statistical.cli --scenario tiny_plan1 --repetitions 100
  python -m tests.statistical.cli --scenario tiny_plan1 --repetitions 50 --backend real_llm
  python -m tests.statistical.cli --scenario tiny_plan1 --repetitions 10 --verbose
        """,
    )
    parser.add_argument(
        "--scenario", "-s",
        type=str,
        default=None,
        help="Scenario name (e.g. tiny_plan1, tiny_plan3, tiny_plan2x2)",
    )
    parser.add_argument(
        "--repetitions", "-n",
        type=int,
        default=None,
        help="Override repetitions count (default: from scenario file)",
    )
    parser.add_argument(
        "--backend", "-b",
        type=str,
        choices=["simulation", "real_llm"],
        default=None,
        help="Override backend selection (default: from scenario file)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-run progress",
    )
    parser.add_argument(
        "--no-thresholds",
        action="store_true",
        help="Skip threshold evaluation",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scenarios and exit",
    )
    args = parser.parse_args()

    # Handle --list
    if args.list:
        scenarios_dir = Path(__file__).resolve().parent.parent / "scenarios"
        print("Available scenarios:")
        for f in sorted(scenarios_dir.glob("*.json")):
            print(f"  {f.stem}")
        return

    if not args.scenario:
        parser.error("--scenario/-s is required (or use --list to see available scenarios)")

    # Resolve and load scenario
    path = _resolve_scenario_path(args.scenario)
    scenario = load_scenario(path)

    # Apply CLI overrides
    if args.repetitions is not None:
        scenario = ConformanceScenario(
            name=scenario.name,
            plan_builder=scenario.plan_builder,
            cycles=scenario.cycles,
            repetitions=args.repetitions,
            backend=args.backend or scenario.backend,
            description=scenario.description,
        )
    elif args.backend is not None:
        scenario = ConformanceScenario(
            name=scenario.name,
            plan_builder=scenario.plan_builder,
            cycles=scenario.cycles,
            repetitions=scenario.repetitions,
            backend=args.backend,
            description=scenario.description,
        )

    # Run
    thresholds = None if args.no_thresholds else Thresholds()
    result = run_scenario(scenario, thresholds=thresholds, verbose=args.verbose)

    # Exit code based on threshold result
    if thresholds is not None:
        from tests.statistical.runner.thresholds import evaluate

        passed, _ = evaluate(result, thresholds)
        sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
