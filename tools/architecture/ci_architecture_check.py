#!/usr/bin/env python
"""
CI wrapper: runs the architecture extractor then the audit.
Exits non-zero if any critical or high issues are found.

Usage:
    python tools/dictionary/ci_architecture_check.py
"""
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
EXTRACTOR = TOOLS_DIR / "extract_architecture.py"
AUDIT = TOOLS_DIR / "audit.py"


def run(script: Path) -> int:
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=TOOLS_DIR.parent.parent,
    )
    return result.returncode


def main() -> int:
    print("=" * 60)
    print("  Architecture CI Check")
    print("=" * 60)

    print("\n-- Step 1: Extracting architecture --\n")
    rc = run(EXTRACTOR)
    if rc != 0:
        print(f"\n[FAIL] Extractor failed (exit code {rc})")
        return rc

    print("\n-- Step 2: Running audit --\n")
    rc = run(AUDIT)
    return rc


if __name__ == "__main__":
    sys.exit(main())
