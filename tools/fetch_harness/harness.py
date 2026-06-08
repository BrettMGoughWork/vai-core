"""
Phase 3.10.6 - Fetch Test Harness
===================================

Standalone CLI tool that loads scenarios from ``scenarios.json``, executes
real HTTP fetches using the appropriate fetch primitive, and reports success
metrics.  Supports multiple fetch modes (simple, hardened) selected per
scenario or via ``--mode``.

Usage::

    python -m tools.fetch_harness.harness                     # run all scenarios
    python -m tools.fetch_harness.harness --hardness simple    # filter by level
    python -m tools.fetch_harness.harness --name httpbin_get   # run one scenario
    python -m tools.fetch_harness.harness --mode hardened      # use hardened fetch
    python -m tools.fetch_harness.harness --json               # JSON output only
    python -m tools.fetch_harness.harness --list               # list scenarios
    python -m tools.fetch_harness.harness --add "name,url,hardness"
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from src.capabilities.primitives.stdlib.http_simple import HttpSimpleFetchPrimitive
from src.core.types.fetch import FetchRequest, FetchResponse

HERE = Path(__file__).resolve().parent
SCENARIOS_PATH = HERE / "scenarios.json"

_PRIMITIVES: dict[str, Any] = {
    "simple": HttpSimpleFetchPrimitive(),
}

try:
    from src.capabilities.primitives.stdlib.http_hardened import (
        HttpHardenedFetchPrimitive,
    )

    _PRIMITIVES["hardened"] = HttpHardenedFetchPrimitive()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def load_scenarios(path: Path = SCENARIOS_PATH) -> list[dict[str, Any]]:
    """Load the scenario list from *path*."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["scenarios"]


def _assess(
    scenario: dict[str, Any], resp: FetchResponse
) -> dict[str, Any]:
    """Assess a fetch result against the scenario's expected characteristics.

    Returns a dict with ``pass``, ``checks`` (list of per-check outcomes),
    and ``notes`` (list of informational observations).
    """
    expect = scenario.get("expect", {})
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    # --- Status code check ---
    expected_status: str | int = expect.get("status_code", "2xx")
    if isinstance(expected_status, int):
        status_ok = resp.status_code == expected_status
    elif isinstance(expected_status, str) and expected_status.endswith("xx"):
        prefix = int(expected_status[0])
        status_ok = resp.status_code is not None and resp.status_code // 100 == prefix
    else:
        status_ok = resp.status_code == int(expected_status)

    checks.append({
        "check": "status_code",
        "expected": str(expected_status),
        "actual": resp.status_code,
        "passed": bool(resp.ok) and status_ok,
    })

    if not resp.ok:
        notes.append(f"Transport failure: {resp.error_type} - {resp.error_message}")

    # --- Body length check ---
    min_len = expect.get("body_min_length", 0)
    actual_len = len(resp.body) if resp.body else 0
    checks.append({
        "check": "body_min_length",
        "expected": min_len,
        "actual": actual_len,
        "passed": actual_len >= min_len,
    })

    # --- Content-type hint ---
    ct_hint = expect.get("content_type_hint")
    if ct_hint and resp.headers:
        actual_ct = resp.headers.get("content-type", resp.headers.get("Content-Type", ""))
        ct_ok = actual_ct.startswith(ct_hint)
        checks.append({
            "check": "content_type",
            "expected": ct_hint,
            "actual": actual_ct,
            "passed": ct_ok,
        })
        if not ct_ok and actual_ct:
            notes.append(f"Content-Type mismatch: expected '{ct_hint}', got '{actual_ct}'")
    elif ct_hint and not resp.headers:
        checks.append({
            "check": "content_type",
            "expected": ct_hint,
            "actual": None,
            "passed": False,
        })
        notes.append("No response headers to check content-type")

    # --- Overall ---
    passed = all(c["passed"] for c in checks)

    return {"passed": passed, "checks": checks, "notes": notes}


def run_scenario(
    scenario: dict[str, Any],
    timeout: float | None = None,
) -> dict[str, Any]:
    """Execute one scenario and return its full result dict.

    The dict is JSON-safe and includes the assessment block.
    """
    req = FetchRequest(
        url=scenario["url"],
        timeout=timeout or 10.0,
    )
    start = time.perf_counter()
    try:
        hardness = scenario.get("hardness", "simple")
        primitive = _PRIMITIVES.get(hardness, _PRIMITIVES["simple"])
        result = primitive.execute(req.to_args(), {})
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if result.status == "success":
            resp = FetchResponse.from_primitive_result(result.data, url=scenario["url"])
        else:
            resp = FetchResponse(
                ok=False,
                elapsed_ms=elapsed_ms,
                url=scenario["url"],
                error_type=result.data.get("error_type", "UnknownError"),
                error_message=result.data.get("error_message", str(result.error or "")),
            )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        resp = FetchResponse(
            ok=False,
            elapsed_ms=elapsed_ms,
            url=scenario["url"],
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    # Summary metrics
    body_len = len(resp.body) if resp.body else 0
    metrics = {
        "success": resp.ok,
        "status_code": resp.status_code,
        "body_length": body_len,
        "elapsed_ms": resp.elapsed_ms,
        "has_cookies": bool(resp.cookies),
    }
    if not resp.ok:
        metrics["error_type"] = resp.error_type
        metrics["error_message"] = resp.error_message

    assessment = _assess(scenario, resp)

    return {
        "scenario": scenario["name"],
        "url": scenario["url"],
        "hardness": scenario.get("hardness", "unknown"),
        "description": scenario.get("description", ""),
        "tags": scenario.get("tags", []),
        "metrics": metrics,
        "assessment": assessment,
    }


def run_all(
    scenarios: list[dict[str, Any]],
    hardness_filter: str | None = None,
    name_filter: str | None = None,
    timeout: float | None = None,
) -> list[dict[str, Any]]:
    """Run a filtered subset of scenarios and return result dicts."""
    results: list[dict[str, Any]] = []
    for sc in scenarios:
        if hardness_filter and sc.get("hardness") != hardness_filter:
            continue
        if name_filter and sc.get("name") != name_filter:
            continue
        results.append(run_scenario(sc, timeout=timeout))
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_table(results: list[dict[str, Any]]) -> None:
    """Print a human-readable summary table."""
    passed = sum(1 for r in results if r["assessment"]["passed"])
    total = len(results)

    print(f"\n{'=' * 72}")
    print(f"  Fetch Test Harness - {passed}/{total} scenarios passed")
    print(f"{'=' * 72}")
    print(f"  {'Scenario':<30} {'Status':<10} {'Code':<6} {'Time':<8} {'Body':<8}")
    print(f"  {'-' * 30} {'-' * 10} {'-' * 6} {'-' * 8} {'-' * 8}")

    for r in results:
        status = "PASS" if r["assessment"]["passed"] else "FAIL"
        code = r["metrics"]["status_code"] or "-"
        elapsed = f"{r['metrics']['elapsed_ms']}ms"
        body = f"{r['metrics']['body_length']}B"
        name = r["scenario"]
        if len(name) > 28:
            name = name[:27] + "..."
        print(f"  {name:<30} {status:<10} {code:<6} {elapsed:<8} {body:<8}")

    print(f"{'-' * 72}")

    # Show failures
    failures = [r for r in results if not r["assessment"]["passed"]]
    if failures:
        print(f"\n  Failures ({len(failures)}):")
        for f in failures:
            notes = f["assessment"]["notes"]
            failed_checks = [
                c for c in f["assessment"]["checks"] if not c["passed"]
            ]
            detail = "; ".join(
                [f"{c['check']}: expected={c['expected']}, got={c['actual']}"
                 for c in failed_checks]
                + notes
            )
            print(f"    X {f['scenario']} - {detail}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch Test Harness - scenario-driven HTTP fetch testing"
    )
    parser.add_argument(
        "--hardness", "-H",
        help="Filter by hardness level (simple, hardened, javascript, spa, antibot)",
    )
    parser.add_argument(
        "--name", "-n",
        help="Run a single scenario by name",
    )
    parser.add_argument(
        "--timeout", "-t", type=float, default=10.0,
        help="Request timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--json", "-j", action="store_true",
        help="Output raw JSON instead of table",
    )
    parser.add_argument(
        "--list", "-l", action="store_true", dest="list_only",
        help="List available scenarios and exit",
    )
    parser.add_argument(
        "--add", "-a",
        help="Quick-add a scenario: \"name,url,hardness\"",
    )

    args = parser.parse_args()

    # Load or create scenarios
    scenarios = load_scenarios()

    # Handle --add
    if args.add:
        parts = [p.strip() for p in args.add.split(",", 2)]
        if len(parts) != 3:
            print("Usage: --add \"name,url,hardness\"", file=sys.stderr)
            sys.exit(1)
        name, url, hardness = parts
        new_scenario = {
            "name": name,
            "url": url,
            "hardness": hardness,
            "description": f"Quick-added scenario: {name}",
            "tags": ["user-added"],
            "expect": {"body_min_length": 0},
        }
        with open(SCENARIOS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        data["scenarios"].append(new_scenario)
        with open(SCENARIOS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Added scenario '{name}' ({hardness}) → {SCENARIOS_PATH}")
        return

    # Handle --list
    if args.list_only:
        print(f"\n{'Scenario':<30} {'Hardness':<12} {'URL'}")
        print(f"{'-' * 30} {'-' * 12} {'-' * 40}")
        for sc in scenarios:
            print(f"{sc['name']:<30} {sc.get('hardness', '?'):<12} {sc['url']}")
        print(f"\n{len(scenarios)} scenarios total")
        return

    # Run
    results = run_all(
        scenarios,
        hardness_filter=args.hardness,
        name_filter=args.name,
        timeout=args.timeout,
    )

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        if not results:
            print("No scenarios matched the filter.")
            return
        # Summary counts
        passed = sum(1 for r in results if r["assessment"]["passed"])
        total = len(results)
        transport_ok = sum(1 for r in results if r["metrics"]["success"])
        print(json.dumps({
            "summary": {
                "total": total,
                "passed": passed,
                "failed": total - passed,
                "transport_ok": transport_ok,
                "transport_failed": total - transport_ok,
            },
            "results": results,
        }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
