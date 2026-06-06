"""
scenario.py — ConformanceScenario definition and loader.

Pure dataclass + loader — no I/O except reading JSON scenario files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class ConformanceScenario:
    """A single statistical conformance scenario.

    Attributes
    ----------
    name : str
        Human-readable name for reporting.
    plan_builder : str
        Name of the plan builder in ``tests.e2e.helpers`` (e.g. ``"plan_1_1"``).
    cycles : int
        Number of agent cycles to run per repetition.
    repetitions : int
        Number of independent runs to perform (default overridden by CLI).
    backend : str
        ``"simulation"`` or ``"real_llm"``.
    description : str
        Optional description for documentation.
    """

    name: str
    plan_builder: str = "plan_1_1"
    cycles: int = 1
    repetitions: int = 50
    backend: str = "simulation"
    description: str = ""


def load_scenario(path: str | Path) -> ConformanceScenario:
    """Load a ConformanceScenario from a JSON file.

    Parameters
    ----------
    path : str or Path
        Path to a ``.json`` scenario file.

    Returns
    -------
    ConformanceScenario
        Immutable scenario object.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    json.JSONDecodeError
        If the file is not valid JSON.
    KeyError
        If a required key is missing.
    """
    with open(path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)

    return ConformanceScenario(
        name=data.get("name", Path(path).stem),
        plan_builder=data.get("plan_builder", "plan_1_1"),
        cycles=data.get("cycles", 1),
        repetitions=data.get("repetitions", 50),
        backend=data.get("backend", "simulation"),
        description=data.get("description", ""),
    )
