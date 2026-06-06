"""
cli.py — Manual entry point for the statistical conformance runner.

Not part of pytest.  Manually executed:

    python -m tests.statistical.cli --scenario tiny_plan1 --repetitions 100

Or:

    python -m tests.statistical.cli --scenario tiny_plan1 --repetitions 10 --backend real_llm --verbose
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.statistical.runner.cli import main

if __name__ == "__main__":
    main()
