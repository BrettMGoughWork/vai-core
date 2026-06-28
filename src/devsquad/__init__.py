"""
DevSquad - multi-agent sprint factory for vai-core
===================================================

A pipeline that takes a human's north-star idea, interviews them to extract
structured sprint parameters, and kicks off an automated workflow: product
manager → architect → engineer → council → review.

Entry points
------------
- ``python -m src.devsquad`` — DevSquad CLI with subcommands
- ``python -m src.devsquad.interview`` — standalone interview agent
- ``from src.devsquad import kickoff_sprint, extract_sprint_params`` — programmatic API
"""

from __future__ import annotations

from .interview import extract_sprint_params, kickoff_sprint, run_interview

__all__ = [
    "extract_sprint_params",
    "kickoff_sprint",
    "run_interview",
]

