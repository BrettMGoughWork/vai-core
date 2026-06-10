"""
quarantine_cli.py — CLI for managing the quarantine pipeline (3.17.4)

Lists pending agent-authored skills and lets a human operator approve or reject them.

Usage:
    python -m tools.quarantine_cli list
    python -m tools.quarantine_cli approve <name>
    python -m tools.quarantine_cli reject <name> [--reason "..."]
    python -m tools.quarantine_cli show <name>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(override=True)

from src.capabilities.registry.skill_registry import CapabilitySkillRegistry


SEP = "-" * 60


def _get_registry() -> CapabilitySkillRegistry:
    return CapabilitySkillRegistry()


def cmd_list(args: argparse.Namespace) -> int:
    """Print all quarantined skills with status."""
    registry = _get_registry()
    if args.all:
        items = registry.quarantine_list_all()
    else:
        items = registry.quarantine_list_pending()

    if not items:
        print("No quarantined skills found.")
        return 0

    print(f"{'Name':<40} {'Status':<12} {'Author':<20}")
    print(SEP)
    for q in items:
        status = "pending" if q.is_pending else ("approved" if q.is_approved else "rejected")
        author = q.provenance.author if q.provenance.author else "-"
        print(f"{q.skill.manifest.name:<40} {status:<12} {author:<20}")

    if args.json:
        print()
        payload = [
            {
                "name": q.skill.manifest.name,
                "status": "pending" if q.is_pending else ("approved" if q.is_approved else "rejected"),
                "author": q.provenance.author,
                "description": q.skill.manifest.description,
                "reason": q.quarantine_reason,
            }
            for q in items
        ]
        json.dump(payload, sys.stdout, indent=2)
        print()

    print(f"\n{len(items)} skill(s) total.")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """Approve a quarantined skill and promote it to the active registry."""
    registry = _get_registry()
    try:
        skill = registry.quarantine_approve(args.name)
        print(f"Approved and registered: {skill.manifest.name}")
        return 0
    except KeyError:
        print(f"Error: no quarantined skill named '{args.name}'", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_reject(args: argparse.Namespace) -> int:
    """Reject a quarantined skill, keeping it in quarantine with rejected status."""
    registry = _get_registry()
    try:
        registry.quarantine_reject(args.name, reason=args.reason)
        print(f"Rejected: {args.name}")
        return 0
    except KeyError:
        print(f"Error: no quarantined skill named '{args.name}'", file=sys.stderr)
        return 1


def cmd_show(args: argparse.Namespace) -> int:
    """Display full details about a quarantined skill."""
    registry = _get_registry()
    q = registry.quarantine_get(args.name)
    if q is None:
        print(f"No quarantined skill named '{args.name}'", file=sys.stderr)
        return 1

    m = q.skill.manifest
    print(f"Name:        {m.name}")
    print(f"Description: {m.description}")
    print(f"Status:      {'pending' if q.is_pending else ('approved' if q.is_approved else 'rejected')}")
    print(f"Reason:      {q.quarantine_reason or '-'}")
    print(f"Author:      {q.provenance.author or '-'}")
    print(f"Created:     {q.provenance.created_at or '-'}")
    print(f"Version:     {q.provenance.version or 1}")
    print(f"Primitives:  {', '.join(m.primitives)}")
    print(f"Steps:       {len(m.steps)}")
    print(f"Inputs:      {json.dumps(m.inputs, indent=2)}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Quarantine governance CLI",
        prog="quarantine",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="List quarantined skills")
    p_list.add_argument("--all", action="store_true", help="Include approved/rejected skills")
    p_list.add_argument("--json", action="store_true", help="Also output machine-readable JSON")
    p_list.set_defaults(func=cmd_list)

    # approve
    p_approve = sub.add_parser("approve", help="Approve a quarantined skill")
    p_approve.add_argument("name", help="Skill name to approve")
    p_approve.set_defaults(func=cmd_approve)

    # reject
    p_reject = sub.add_parser("reject", help="Reject a quarantined skill")
    p_reject.add_argument("name", help="Skill name to reject")
    p_reject.add_argument("--reason", default="rejected by governance", help="Reason for rejection")
    p_reject.set_defaults(func=cmd_reject)

    # show
    p_show = sub.add_parser("show", help="Show details about a quarantined skill")
    p_show.add_argument("name", help="Skill name to inspect")
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
