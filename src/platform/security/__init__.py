"""
S4.9.3 — Security Hardening for Stratum-4.

Enforces baseline safety guarantees across all S4 components:
authentication, rate limiting, input validation, and sandboxing.
"""

from src.platform.security.hardening import (
    SecurityResult,
    check_auth,
    RateLimiter,
    check_rate_limit,
    validate_input,
    validate_job_payload,
    validate_instruction,
    SandboxConfig,
    sandbox_execute,
)

__all__ = [
    "SecurityResult",
    "check_auth",
    "RateLimiter",
    "check_rate_limit",
    "validate_input",
    "validate_job_payload",
    "validate_instruction",
    "SandboxConfig",
    "sandbox_execute",
]
