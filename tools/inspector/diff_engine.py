"""
Deep JSON diff engine for cycle trace comparison.

Pure function, stdlib only, no side effects.
"""

from __future__ import annotations

import json
from typing import Any


def diff_cycles(prev: dict, curr: dict) -> dict:
    """
    Compute a deep diff between two cycle dicts.

    Returns:
        {
            "added":     { dotted.key: value }   # in curr, not in prev
            "removed":   { dotted.key: value }   # in prev, not in curr
            "changed":   { dotted.key: {"from": ..., "to": ...} }
            "unchanged": { dotted.key: value }
        }
    """
    result: dict[str, dict] = {"added": {}, "removed": {}, "changed": {}, "unchanged": {}}
    _diff_dicts(prev, curr, result, "")
    return result


def _diff_dicts(prev: dict, curr: dict, result: dict, path: str) -> None:
    all_keys = set(prev.keys()) | set(curr.keys())
    for key in sorted(all_keys):
        full_key = f"{path}.{key}" if path else key
        if key not in prev:
            result["added"][full_key] = curr[key]
        elif key not in curr:
            result["removed"][full_key] = prev[key]
        else:
            pval, cval = prev[key], curr[key]
            if isinstance(pval, dict) and isinstance(cval, dict):
                _diff_dicts(pval, cval, result, full_key)
            elif isinstance(pval, list) and isinstance(cval, list):
                if pval != cval:
                    result["changed"][full_key] = {"from": pval, "to": cval}
                else:
                    result["unchanged"][full_key] = cval
            elif pval != cval:
                result["changed"][full_key] = {"from": pval, "to": cval}
            else:
                result["unchanged"][full_key] = cval


def format_diff_rich(diff: dict) -> str:
    """
    Format a diff dict as Rich-markup lines with +/-/~ markers.

    Colour coding:
        green  = added
        red    = removed
        yellow = changed
    """
    lines: list[str] = []

    for key, val in sorted(diff.get("added", {}).items()):
        lines.append(f"[green]+ {key}:[/green] {_compact(val)}")

    for key, val in sorted(diff.get("removed", {}).items()):
        lines.append(f"[red]- {key}:[/red] {_compact(val)}")

    for key, change in sorted(diff.get("changed", {}).items()):
        lines.append(
            f"[yellow]~ {key}:[/yellow] "
            f"[dim]{_compact(change['from'])}[/dim] → {_compact(change['to'])}"
        )

    if not lines:
        lines.append("[dim](no changes)[/dim]")

    return "\n".join(lines)


def format_json_rich(data: Any, indent: int = 2) -> str:
    """Return a pretty-printed JSON string (no Rich markup — use with Syntax widget)."""
    return json.dumps(data, indent=indent, default=str)


def _compact(val: Any) -> str:
    if isinstance(val, (dict, list)):
        s = json.dumps(val, default=str)
        return s[:120] + "…" if len(s) > 120 else s
    return str(val)
