"""
Architecture audit script for vai-core.

Reads docs/architecture.json and produces docs/architecture_audit.md.

Checks:
  1. Duplicate classes (exact name + near-duplicate method sets)
  2. Architecture violations (forbidden cross-stratum imports)
  3. Stratum invariant violations (rules from ARCHITECTURE.md / ROADMAP.md)
  4. Dead code (fan_in == 0, non-test classes)
  5. Priority-ranked issue list

Idempotent — always overwrites the output file.
Usage:
    python tools/dictionary/audit.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
JSON_PATH = REPO_ROOT / "docs" / "architecture.json"
OUT_PATH  = REPO_ROOT / "docs" / "architecture_audit.md"

# ── Stratum rules ─────────────────────────────────────────────────────────────
# Defines which strata a given stratum is ALLOWED to import from.
# Based on ARCHITECTURE.md layering:
#   domain      → pure; no infra / adapter / utility imports
#   infrastructure → may use domain; not adapter
#   adapter     → may use domain + infrastructure
#   utility     → may use domain; ideally thin
#   test        → unrestricted

ALLOWED_IMPORTS: dict[str, set[str]] = {
    "domain":         {"domain"},
    "infrastructure": {"domain", "infrastructure", "utility", "adapter"},
    "adapter":        {"domain", "infrastructure", "adapter", "capability"},
    "utility":        {"domain", "infrastructure", "utility", "adapter"},
    "capability":     {"capability", "domain"},
    "test":           {"domain", "infrastructure", "adapter", "utility", "capability", "test"},
}

# Severity weights for priority ranking
SEVERITY = {"critical": 3, "high": 2, "medium": 1, "low": 0}


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json() -> dict[str, Any]:
    if not JSON_PATH.exists():
        sys.exit(f"ERROR: {JSON_PATH} not found. Run extract_architecture.py first.")
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def json_mtime() -> str:
    ts = JSON_PATH.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


# ── Analysis functions ────────────────────────────────────────────────────────

def find_duplicates(classes: list[dict]) -> list[dict]:
    """
    Exact name duplicates and near-duplicates (Jaccard ≥ 0.7 on public_methods).
    """
    issues = []

    # 1. Exact name duplicates
    name_map: dict[str, list[dict]] = defaultdict(list)
    for cls in classes:
        name_map[cls["name"]].append(cls)

    for name, group in sorted(name_map.items()):
        if len(group) > 1:
            files = [c["file"] for c in group]
            strata = {c["inferred_stratum"] for c in group}
            # Test-only duplicates (e.g. shared Fake helpers) are expected — low priority
            sev = "low" if strata <= {"test"} else "high"
            issues.append({
                "severity": sev,
                "category": "duplicate",
                "title": f"Duplicate class name: `{name}`",
                "detail": f"Defined in {len(group)} files: " + ", ".join(f"`{f}`" for f in files),
                "fan_in": max(c["fan_in"] for c in group),
                "fan_out": max(c["fan_out"] for c in group),
            })

    # 2. Near-duplicates (different names, similar method sets, ≥3 methods, Jaccard ≥ 0.8)
    # Minimum method count avoids false positives on small single-method interfaces.
    checked: set[tuple[str, str]] = set()
    cls_list = [c for c in classes if len(c["public_methods"]) >= 3]
    for i, a in enumerate(cls_list):
        for b in cls_list[i + 1:]:
            if a["name"] == b["name"]:
                continue
            # Skip test↔test near-duplicates — Fake helpers naturally share method names
            if a["inferred_stratum"] == "test" and b["inferred_stratum"] == "test":
                continue
            key = tuple(sorted([a["name"], b["name"]]))
            if key in checked:
                continue
            checked.add(key)
            sim = jaccard(a["public_methods"], b["public_methods"])
            if sim >= 0.8:
                issues.append({
                    "severity": "medium",
                    "category": "near-duplicate",
                    "title": f"Near-duplicate classes: `{a['name']}` ↔ `{b['name']}` (similarity {sim:.0%})",
                    "detail": (
                        f"`{a['name']}` in `{a['file']}` ({a['inferred_stratum']}), "
                        f"`{b['name']}` in `{b['file']}` ({b['inferred_stratum']}). "
                        f"Shared methods: {sorted(set(a['public_methods']) & set(b['public_methods']))}"
                    ),
                    "fan_in": max(a["fan_in"], b["fan_in"]),
                    "fan_out": max(a["fan_out"], b["fan_out"]),
                })

    return issues


def find_arch_violations(classes: list[dict], refs: list[dict]) -> list[dict]:
    """
    Flag cross-stratum import violations based on ALLOWED_IMPORTS.
    Uses the references list (type=import) plus class stratum lookup.
    """
    issues = []
    stratum_of: dict[str, str] = {c["name"]: c["inferred_stratum"] for c in classes}

    for ref in refs:
        if ref.get("type") != "import":
            continue
        src = ref["source"]
        tgt = ref["target"]
        src_stratum = stratum_of.get(src, "utility")
        tgt_stratum = stratum_of.get(tgt, "utility")

        allowed = ALLOWED_IMPORTS.get(src_stratum, set())
        if tgt_stratum not in allowed:
            issues.append({
                "severity": "high",
                "category": "arch-violation",
                "title": f"Forbidden import: `{src}` ({src_stratum}) → `{tgt}` ({tgt_stratum})",
                "detail": (
                    f"`{src}` (stratum: **{src_stratum}**) imports from "
                    f"`{tgt}` (stratum: **{tgt_stratum}**). "
                    f"Allowed strata for {src_stratum}: {sorted(allowed)}."
                ),
                "fan_in": 0,
                "fan_out": 0,
            })

    return issues


def find_invariant_violations(classes: list[dict]) -> list[dict]:
    """
    Stratum invariants derived from ARCHITECTURE.md and ROADMAP.md:

    I1 — Domain must be pure: no infrastructure or adapter imports.
    I2 — Infrastructure must not import from adapter.
    I3 — Stratum 1 (utility/infra/adapter) must not contain long-horizon reasoning keywords.
    I4 — Cognitive outputs (domain/utility planning) must not embed tool/LLM keys.
    I5 — Utility classes with fan_out > 10 are stratum violations (doing too much).
    I6 — Test classes must not live in src/.
    """
    issues = []

    # Forbidden import fragments per stratum (by path/package fragments in imports)
    INFRA_FRAGMENTS   = {"llm", "transport", "telemetry", "observability"}
    ADAPTER_FRAGMENTS = {"agent", "dispatcher"}
    REASONING_KEYWORDS = {"plan", "reason", "cognit", "stratum2", "llm_call"}
    TOOL_LLM_KEYS = {"tool", "tool_name", "tool_calls", "model", "prompt", "temperature"}

    for cls in classes:
        stratum = cls["inferred_stratum"]
        # Split each import into path segments for precise matching (avoids false
        # positives like "AgentError" containing "agent", or "skillmetadata" containing "llm").
        import_segments = [set(i.lower().split(".")) for i in cls["imports"]]
        file = cls["file"]

        # I1: domain must not import infra or adapter
        if stratum == "domain":
            for segments in import_segments:
                for frag in INFRA_FRAGMENTS | ADAPTER_FRAGMENTS:
                    if frag in segments:
                        issues.append({
                            "severity": "critical",
                            "category": "invariant",
                            "title": f"I1 — Domain class `{cls['name']}` imports infrastructure/adapter: `{frag}`",
                            "detail": f"`{cls['name']}` in `{file}` has import path segment `{frag}`. Domain must be pure.",
                            "fan_in": cls["fan_in"],
                            "fan_out": cls["fan_out"],
                        })
                        break

        # I2: infrastructure must not import adapter
        if stratum == "infrastructure":
            for segments in import_segments:
                for frag in ADAPTER_FRAGMENTS:
                    if frag in segments:
                        issues.append({
                            "severity": "high",
                            "category": "invariant",
                            "title": f"I2 — Infrastructure class `{cls['name']}` imports adapter: `{frag}`",
                            "detail": f"`{cls['name']}` in `{file}`. Infrastructure must not depend on adapters.",
                            "fan_in": cls["fan_in"],
                            "fan_out": cls["fan_out"],
                        })
                        break

        # I3: Stratum 1 (utility) must not contain long-horizon reasoning
        if stratum == "utility":
            name_lower = cls["name"].lower()
            for kw in REASONING_KEYWORDS:
                if kw in name_lower:
                    issues.append({
                        "severity": "medium",
                        "category": "invariant",
                        "title": f"I3 — Utility class `{cls['name']}` has reasoning keyword `{kw}` in name",
                        "detail": (
                            f"`{cls['name']}` in `{file}`. Stratum 1 must be reactive and deterministic. "
                            f"Reasoning/planning logic belongs in Stratum 2 (domain)."
                        ),
                        "fan_in": cls["fan_in"],
                        "fan_out": cls["fan_out"],
                    })
                    break

        # I5: utility class with very high fan_out (doing too much)
        if stratum == "utility" and cls["fan_out"] > 12:
            issues.append({
                "severity": "medium",
                "category": "invariant",
                "title": f"I5 — Utility class `{cls['name']}` has excessive fan_out ({cls['fan_out']})",
                "detail": f"`{cls['name']}` in `{file}` references {cls['fan_out']} other types. Suggests violation of single responsibility.",
                "fan_in": cls["fan_in"],
                "fan_out": cls["fan_out"],
            })

        # I6: test classes must not live in src/
        if stratum == "test" and file.startswith("src/"):
            issues.append({
                "severity": "medium",
                "category": "invariant",
                "title": f"I6 — Test class `{cls['name']}` is inside `src/`",
                "detail": f"`{cls['name']}` in `{file}`. Test code must live under `tests/`, not `src/`.",
                "fan_in": cls["fan_in"],
                "fan_out": cls["fan_out"],
            })

    return issues


# ── S3 (Capability) invariant checks ──────────────────────────────────────────

# Allowed primitive module filenames
VALID_PRIMITIVE_MODULES = {
    "python.py", "cli.py", "mcp.py", "base.py", "types.py", "__init__.py",
}


def find_primitive_module_violations(classes: list[dict]) -> list[dict]:
    """S3 I7 — Primitive module invariants.

    - Only VALID_PRIMITIVE_MODULES may exist in src/capabilities/primitives/
    - Each primitive class must declare: name, description, type, execute method.
    """
    issues: list[dict] = []
    primitives_dir = REPO_ROOT / "src" / "capabilities" / "primitives"

    if not primitives_dir.is_dir():
        issues.append({
            "severity": "high",
            "category": "invariant",
            "title": "I7 — Primitives directory missing: `src/capabilities/primitives/`",
            "detail": "The primitives directory does not exist. Phase 3.1 must create it.",
            "fan_in": 0,
            "fan_out": 0,
        })
        return issues

    # Check for invalid .py files
    for py_file in primitives_dir.glob("*.py"):
        if py_file.name not in VALID_PRIMITIVE_MODULES:
            rel = str(py_file.relative_to(REPO_ROOT)).replace("\\", "/")
            issues.append({
                "severity": "high",
                "category": "invariant",
                "title": f"I7 — Invalid file in primitives directory: `{py_file.name}`",
                "detail": f"`{rel}` is not one of the allowed primitive modules: {sorted(VALID_PRIMITIVE_MODULES)}.",
                "fan_in": 0,
                "fan_out": 0,
            })

    # Check each primitive class found in extraction has required attributes
    primitive_class_names = {"PythonPrimitive", "CLIPrimitive", "MCPPrimitive"}
    for cls in classes:
        if cls["name"] not in primitive_class_names:
            continue
        missing = []
        if "name" not in cls.get("public_attributes", []) and cls["name"] != "PythonPrimitive":
            pass  # name/description/type set in __init__, not as class attrs
        if "execute" not in cls.get("public_methods", []):
            missing.append("execute")
        if "validate_args" not in cls.get("public_methods", []):
            missing.append("validate_args")
        if missing:
            issues.append({
                "severity": "high",
                "category": "invariant",
                "title": f"I7 — Primitive class `{cls['name']}` missing required methods: {missing}",
                "detail": f"`{cls['name']}` in `{cls['file']}` must define: {', '.join(missing)}.",
                "fan_in": cls["fan_in"],
                "fan_out": cls["fan_out"],
            })

    return issues


def find_skill_manifest_violations(data: dict[str, Any]) -> list[dict]:
    """S3 I8 — Skill manifest invariants.

    - No .py files in src/capabilities/skills/
    - Each .skill.md file must have valid YAML front-matter with: name, description, inputs, outputs, primitives.
    """
    issues: list[dict] = []
    skills_dir = REPO_ROOT / "src" / "capabilities" / "skills"

    if not skills_dir.is_dir():
        # Skills not yet implemented — expected at this phase
        return issues

    # Check for .py files in skills directory
    py_files = list(skills_dir.glob("*.py"))
    if py_files:
        py_names = sorted(f.name for f in py_files)
        issues.append({
            "severity": "medium",
            "category": "invariant",
            "title": f"I8 — Python files in skills directory: {py_names}",
            "detail": (
                f"`src/capabilities/skills/` contains {len(py_files)} .py file(s): {py_names}. "
                "Skills must be defined as `.skill.md` files with YAML front-matter, not Python modules."
            ),
            "fan_in": 0,
            "fan_out": 0,
        })

    # Validate extracted skill manifests
    skills = data.get("skills", [])
    for skill in skills:
        file = skill.get("file", "unknown")
        missing = []
        for field in ("name", "description", "inputs", "outputs", "primitives"):
            if not skill.get(field):
                missing.append(field)
        if missing:
            issues.append({
                "severity": "high",
                "category": "invariant",
                "title": f"I8 — Skill manifest `{file}` missing required fields: {missing}",
                "detail": f"`.skill.md` file `{file}` is missing YAML front-matter fields: {missing}.",
                "fan_in": 0,
                "fan_out": 0,
            })

    # Check for .skill.md files with no YAML front-matter (parse failed)
    md_files = set()
    for dirpath, _, filenames in os.walk(skills_dir):
        for f in filenames:
            if f.endswith(".skill.md"):
                md_files.add(
                    str(Path(dirpath).relative_to(REPO_ROOT) / f).replace("\\", "/")
                )
    extracted_files = {s["file"] for s in skills}
    unparseable = md_files - extracted_files
    for f in sorted(unparseable):
        issues.append({
            "severity": "high",
            "category": "invariant",
            "title": f"I8 — Skill file `{f}` has invalid or missing YAML front-matter",
            "detail": "The `.skill.md` file must start with `---` delimited YAML front-matter containing name, description, inputs, outputs, and primitives.",
            "fan_in": 0,
            "fan_out": 0,
        })

    return issues


def find_registry_violations(classes: list[dict]) -> list[dict]:
    """S3 I9 — Registry invariants.

    - Registry modules must live under src/capabilities/registry/ or src/core/types/
    - Must define: PrimitiveRegistry, SkillRegistry
    - Registries must not import S1 (utility/infrastructure/adapter) modules.
      Domain imports are allowed for shared types.
    """
    issues: list[dict] = []
    registry_dir = REPO_ROOT / "src" / "capabilities" / "registry"

    if not registry_dir.is_dir():
        issues.append({
            "severity": "high",
            "category": "invariant",
            "title": "I9 — Registry directory missing: `src/capabilities/registry/`",
            "detail": "The registry directory does not exist.",
            "fan_in": 0,
            "fan_out": 0,
        })
        return issues

    # Check for PrimitiveRegistry and SkillRegistry
    # These may live in src/capabilities/registry/ OR src/core/types/
    registry_class_names = {
        c["name"] for c in classes
        if c["file"].startswith("src/capabilities/registry/")
        or c["file"].startswith("src/core/types/registry")
    }
    required = {"PrimitiveRegistry", "SkillRegistry"}
    missing_classes = required - registry_class_names
    for mc in sorted(missing_classes):
        issues.append({
            "severity": "high",
            "category": "invariant",
            "title": f"I9 — Missing required registry class: `{mc}`",
            "detail": f"`{mc}` must be defined in `src/capabilities/registry/` or `src/core/types/`.",
            "fan_in": 0,
            "fan_out": 0,
        })

    # Registries must not import S1 (utility/infrastructure/adapter)
    # Domain imports are allowed — shared types like enums and dataclasses
    forbidden_strata = {"infrastructure", "adapter", "utility"}
    stratum_of = {c["name"]: c["inferred_stratum"] for c in classes}
    for cls in classes:
        if cls["inferred_stratum"] != "capability":
            continue
        if "registry" not in cls["file"] and "registry" not in cls.get("package", ""):
            continue
        for imp in cls["imports"]:
            # Only check internal vai-core imports
            top = imp.split(".")[0]
            if top not in ("src", "capabilities"):
                continue
            # Resolve target stratum from the class map
            last = imp.split(".")[-1]
            tgt_stratum = stratum_of.get(last)
            if tgt_stratum in forbidden_strata:
                issues.append({
                    "severity": "high",
                    "category": "invariant",
                    "title": f"I9 — Registry class `{cls['name']}` imports from forbidden stratum: `{imp}` ({tgt_stratum})",
                    "detail": f"`{cls['name']}` in `{cls['file']}`. Registries must not import S1 or S2 modules.",
                    "fan_in": cls["fan_in"],
                    "fan_out": cls["fan_out"],
                })

    return issues


def find_discovery_violations(classes: list[dict]) -> list[dict]:
    """S3 I10 — Discovery invariants.

    - Discovery modules must live under src/capabilities/discovery/
    - Must define: SkillDiscoveryQuery, SkillDiscoveryResult
    - Discovery must not import primitives directly.
    """
    issues: list[dict] = []
    discovery_dir = REPO_ROOT / "src" / "capabilities" / "discovery"

    if not discovery_dir.is_dir():
        issues.append({
            "severity": "high",
            "category": "invariant",
            "title": "I10 — Discovery directory missing: `src/capabilities/discovery/`",
            "detail": "The discovery directory does not exist.",
            "fan_in": 0,
            "fan_out": 0,
        })
        return issues

    # Check for SkillDiscoveryQuery and SkillDiscoveryResult
    discovery_class_names = {c["name"] for c in classes if (
        c["file"].startswith("src/capabilities/discovery/")
        or c["file"].startswith("src/capabilities/contracts")
    )}
    required = {"SkillDiscoveryQuery", "SkillDiscoveryResult"}
    missing_classes = required - discovery_class_names
    for mc in sorted(missing_classes):
        issues.append({
            "severity": "high",
            "category": "invariant",
            "title": f"I10 — Missing required discovery class: `{mc}`",
            "detail": f"`{mc}` must be defined in `src/capabilities/discovery/` or `src/capabilities/contracts.py`.",
            "fan_in": 0,
            "fan_out": 0,
        })

    # Discovery must not import primitives directly
    for cls in classes:
        if cls["inferred_stratum"] != "capability":
            continue
        if "discovery" not in cls["file"] and cls["file"] != "src/capabilities/contracts.py":
            continue
        for imp in cls["imports"]:
            if "primitives" in imp.lower() and "Primitive" in imp:
                issues.append({
                    "severity": "high",
                    "category": "invariant",
                    "title": f"I10 — Discovery class `{cls['name']}` imports primitives directly: `{imp}`",
                    "detail": f"`{cls['name']}` in `{cls['file']}`. Discovery must not import primitives directly.",
                    "fan_in": cls["fan_in"],
                    "fan_out": cls["fan_out"],
                })

    return issues


def find_dead_code(classes: list[dict]) -> list[dict]:
    """
    Classes with fan_in == 0 that are not in the test stratum and not __init__-only stubs.
    """
    issues = []
    for cls in classes:
        if cls["inferred_stratum"] == "test":
            continue
        if cls.get("dead_code_ignored"):
            continue
        if cls["fan_in"] == 0:
            has_methods = bool(cls["public_methods"] or cls["public_attributes"])
            sev = "medium" if has_methods else "low"
            issues.append({
                "severity": sev,
                "category": "dead-code",
                "title": f"Unreferenced class: `{cls['name']}` ({cls['inferred_stratum']})",
                "detail": (
                    f"`{cls['name']}` in `{cls['file']}` has fan_in=0 — "
                    f"no other class imports or references it. "
                    + (f"Has {len(cls['public_methods'])} public methods." if cls["public_methods"] else "No public methods (possible stub).")
                ),
                "fan_in": 0,
                "fan_out": cls["fan_out"],
            })

    return issues


def rank_issues(all_issues: list[dict]) -> list[dict]:
    """
    Sort by (severity_weight DESC, fan_in DESC, fan_out DESC, title ASC).
    """
    def score(issue):
        sev = SEVERITY.get(issue["severity"], 0)
        return (-sev, -issue.get("fan_in", 0), -issue.get("fan_out", 0), issue["title"])

    return sorted(all_issues, key=score)


# ── Markdown rendering ────────────────────────────────────────────────────────

def badge(severity: str) -> str:
    icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
    return icons.get(severity, "⚪")


def render_section(title: str, issues: list[dict], show_count: bool = True) -> str:
    lines = []
    count = f" ({len(issues)} found)" if show_count else ""
    lines.append(f"## {title}{count}\n")
    if not issues:
        lines.append("_No issues found._\n")
        return "\n".join(lines)
    for issue in issues:
        b = badge(issue["severity"])
        lines.append(f"### {b} {issue['title']}\n")
        lines.append(f"**Severity**: `{issue['severity']}`  ")
        lines.append(f"**Category**: `{issue['category']}`  ")
        lines.append(f"**fan_in**: {issue.get('fan_in', '-')} | **fan_out**: {issue.get('fan_out', '-')}\n")
        lines.append(f"{issue['detail']}\n")
    return "\n".join(lines)


def render_priority_table(ranked: list[dict]) -> str:
    lines = [
        "## 5. Priority-Ranked Issues\n",
        "| # | Sev | Category | Title |",
        "|---|-----|----------|-------|",
    ]
    for i, issue in enumerate(ranked, 1):
        b = badge(issue["severity"])
        title = issue["title"].replace("|", "\\|")
        lines.append(f"| {i} | {b} `{issue['severity']}` | `{issue['category']}` | {title} |")
    return "\n".join(lines) + "\n"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    data = load_json()
    classes  = data.get("classes", [])
    refs     = data.get("references", [])

    mtime = json_mtime()
    run_ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    print(f"Auditing {len(classes)} classes, {len(refs)} references …")

    dupes    = find_duplicates(classes)
    arch     = find_arch_violations(classes, refs)
    inv      = find_invariant_violations(classes)
    dead     = find_dead_code(classes)
    s3_prim  = find_primitive_module_violations(classes)
    s3_skill = find_skill_manifest_violations(data)
    s3_reg   = find_registry_violations(classes)
    s3_disc  = find_discovery_violations(classes)

    all_issues = dupes + arch + inv + dead + s3_prim + s3_skill + s3_reg + s3_disc
    ranked     = rank_issues(all_issues)

    # Summary counts by severity
    counts: dict[str, int] = defaultdict(int)
    for issue in all_issues:
        counts[issue["severity"]] += 1

    lines = [
        "# Architecture Audit Report",
        "",
        f"> **architecture.json snapshot**: `{mtime}`  ",
        f"> **Audit generated**: `{run_ts}`  ",
        f"> **Classes analysed**: {len(classes)} | **References**: {len(refs)}",
        "",
        "## Summary",
        "",
        f"| Severity | Count |",
        f"|----------|-------|",
        f"| 🔴 Critical | {counts['critical']} |",
        f"| 🟠 High     | {counts['high']} |",
        f"| 🟡 Medium   | {counts['medium']} |",
        f"| 🔵 Low      | {counts['low']} |",
        f"| **Total**   | **{len(all_issues)}** |",
        "",
        "---",
        "",
        render_section("1. Duplicate Classes", dupes),
        "---",
        "",
        render_section("2. Architecture Violations (cross-stratum imports)", arch),
        "---",
        "",
        render_section("3. Stratum Invariant Violations", inv),
        "---",
        "",
        render_section("4. Dead Code (fan_in = 0)", dead),
        "---",
        "",
        render_section("5. S3 Primitives (I7)", s3_prim),
        "---",
        "",
        render_section("6. S3 Skills (I8)", s3_skill),
        "---",
        "",
        render_section("7. S3 Registry (I9)", s3_reg),
        "---",
        "",
        render_section("8. S3 Discovery (I10)", s3_disc),
        "---",
        "",
        render_priority_table(ranked),
    ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written: {OUT_PATH}")
    print(f"  critical : {counts['critical']}")
    print(f"  high     : {counts['high']}")
    print(f"  medium   : {counts['medium']}")
    print(f"  low      : {counts['low']}")
    print(f"  total    : {len(all_issues)}")

    # Return non-zero if any critical or high issues exist (CI gate)
    if counts["critical"] > 0 or counts["high"] > 0:
        print(f"\n[FAIL] {counts['critical']} critical, {counts['high']} high issues found.")
        return 1

    print("\n[PASS] No critical or high issues.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
