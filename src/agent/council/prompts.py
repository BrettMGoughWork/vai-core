"""
Council Prompt Builders — construct phase-specific prompts for council members.

Each builder returns a fully-formed prompt string that provides the
council member with the context they need for their role in that phase,
without leaking information they should not see.
"""

from __future__ import annotations

from typing import Dict


def build_analysis_prompt(
    problem: str,
    member_id: str,
    *,
    max_tokens: int = 2000,
) -> str:
    """Prompt a council member for their independent analysis.

    Parameters
    ----------
    problem:
        The problem statement put to the council.
    member_id:
        The agent being prompted (for persona-aware instructions).
    max_tokens:
        Approximate output length guidance.

    Returns
    -------
    str:
        The analysis prompt.
    """
    return (
        f"You are a council member ('{member_id}').\n\n"
        f"## Problem\n{problem}\n\n"
        f"## Instructions\n"
        f"Provide your independent analysis of the above problem from "
        f"your specific perspective. Be concise and structured.\n\n"
        f"Use the following format:\n"
        f"  Analysis: <your reasoning>\n"
        f"  Recommendation: <your proposed course of action>\n"
        f"  Assumptions: <key assumptions underlying your analysis>\n"
        f"  Risks: <risks you identify>\n\n"
        f"Limit your response to approximately {max_tokens} tokens."
    )


def build_counter_prompt(
    problem: str,
    member_id: str,
    other_analyses: Dict[str, str],
    *,
    max_tokens: int = 1500,
) -> str:
    """Prompt a council member to counter-analyse **other** members.

    The member's own analysis is intentionally excluded — they see only
    what the other members said. Defensively filters out the member's
    own analysis even if it appears in *other_analyses*.

    Parameters
    ----------
    problem:
        The problem statement put to the council.
    member_id:
        The agent being prompted.
    other_analyses:
        Map of *other* member_agent_id → their analysis text.
    max_tokens:
        Approximate output length guidance.

    Returns
    -------
    str:
        The counter-analysis prompt.
    """
    # Defensive filter: exclude the member's own analysis
    filtered = {
        mid: text
        for mid, text in other_analyses.items()
        if mid != member_id
    }
    analyses_section = "\n\n".join(
        f"### Analysis by {mid}\n{text}"
        for mid, text in filtered.items()
    )

    return (
        f"You are a council member ('{member_id}').\n\n"
        f"## Problem\n{problem}\n\n"
        f"## Other Members' Analyses\n{analyses_section}\n\n"
        f"## Instructions\n"
        f"Review the analyses from the OTHER council members above "
        f"(your own analysis is excluded). Provide counter-analysis:\n"
        f"- Points you agree with and why\n"
        f"- Flaws or gaps you identify\n"
        f"- Overlooked considerations\n"
        f"- How your perspective differs\n\n"
        f"Do NOT simply repeat your original analysis. Engage directly "
        f"with what the others said.\n\n"
        f"Limit your response to approximately {max_tokens} tokens."
    )


def build_arbitration_prompt(
    problem: str,
    analyses: Dict[str, str],
    counters: Dict[str, str],
) -> str:
    """Prompt the arbitrator to synthesise a final decision.

    The arbitrator sees ALL analyses and counter-analyses.

    Parameters
    ----------
    problem:
        The problem statement put to the council.
    analyses:
        Map of member_agent_id → analysis text.
    counters:
        Map of member_agent_id → counter-analysis text.

    Returns
    -------
    str:
        The arbitration prompt.
    """
    analyses_section = "\n\n".join(
        f"### {mid} — Analysis\n{text}"
        for mid, text in analyses.items()
    )
    counters_section = "\n\n".join(
        f"### {mid} — Counter-Analysis\n{text}"
        for mid, text in counters.items()
    )

    return (
        f"You are the impartial arbitrator for this council.\n\n"
        f"## Problem\n{problem}\n\n"
        f"## All Analyses\n{analyses_section}\n\n"
        f"## All Counter-Analyses\n{counters_section}\n\n"
        f"## Instructions\n"
        f"Weigh all perspectives impartially and produce a final "
        f"decision. Consider the strength of each argument, alignment "
        f"with stated goals, and identified risks.\n\n"
        f"Output your decision in this exact format:\n"
        f"  Decision: <clear statement of the decision>\n"
        f"  Rationale: <reasoning referencing key points>\n"
        f"  Confidence: <HIGH | MEDIUM | LOW>\n"
        f"  Dissent Notes: <any minority opinions or concerns>\n\n"
        f"If equally valid paths exist, pick one and explain why."
    )
