"""
S2↔S3 boundary contracts.

These are pure dataclasses with NO imports from src/core/ or src/runtime/.
They define the shape of inter-stratum communication between Stratum 2
(Planning + Execution) and Stratum 3 (Capabilities).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SkillCallRequest:
    """Request from S2 to S3 to execute a skill."""

    skill_name: str
    """Fully-qualified skill name (e.g. 'file.read', 'json.parse')."""

    arguments: Dict[str, Any] = field(default_factory=dict)
    """Keyword arguments to pass to the skill's handler."""

    timeout_ms: Optional[int] = None
    """Optional execution timeout in milliseconds."""

    idempotency_key: Optional[str] = None
    """Optional key for idempotent execution tracking."""


@dataclass
class SkillResult:
    """Response from S3 to S2 after skill execution."""

    skill_name: str
    """The skill that was executed."""

    success: bool
    """Whether execution succeeded without error."""

    output: Any = None
    """The skill's return value on success."""

    error: Optional[str] = None
    """Error message on failure."""

    error_type: Optional[str] = None
    """Machine-readable error category (e.g. 'ValidationError', 'TimeoutError')."""

    duration_ms: Optional[float] = None
    """Wall-clock execution time in milliseconds."""

    output_schema_snapshot: Optional[Dict[str, Any]] = None
    """Snapshot of the output schema used for validation (debug/audit)."""


@dataclass
class SkillDiscoveryQuery:
    """Request from S2 to S3 to discover available skills."""

    query: Optional[str] = None
    """Natural-language query describing the desired capability."""

    domain: Optional[str] = None
    """Filter by domain (e.g. 'file', 'network', 'text')."""

    input_type_hint: Optional[str] = None
    """Hint about expected input type."""

    output_type_hint: Optional[str] = None
    """Hint about desired output type."""

    max_results: int = 10
    """Maximum number of results to return."""

    include_disabled: bool = False
    """Whether to include disabled skills in results."""


@dataclass
class SkillDiscoveryResult:
    """Response from S3 to S2 with discovered skills."""

    query: Optional[str]
    """Echo of the original query for correlation."""

    skills: List[DiscoveredSkill] = field(default_factory=list)
    """Ranked list of matching skills."""

    total_count: int = 0
    """Total number of matching skills before truncation."""


@dataclass
class DiscoveredSkill:
    """Summary of a skill returned by discovery."""

    name: str
    """Fully-qualified skill name."""

    description: str
    """Human-readable description from the skill manifest."""

    input_schema: Dict[str, Any] = field(default_factory=dict)
    """JSON Schema for the skill's inputs."""

    output_schema: Optional[Dict[str, Any]] = None
    """JSON Schema for the skill's outputs (if declared)."""

    domains: List[str] = field(default_factory=list)
    """Tags/domains this skill belongs to."""

    cost_hint: int = 0
    """Estimated relative cost (0 = free, higher = more expensive)."""

    relevance_score: float = 0.0
    """Relevance score from discovery search (0.0–1.0)."""
