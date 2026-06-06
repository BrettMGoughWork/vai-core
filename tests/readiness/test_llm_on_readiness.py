"""
Phase 2.14.6 — LLM-On Readiness CI Gate
========================================

CI test that enforces the LLM-On readiness checklist.
If any readiness condition is not met, this test fails.
"""

import pytest

from src.core.planning.s1_contract.readiness import (
    ReadinessResult,
    check_llm_on_readiness,
    render_readiness_status,
)


class TestLLMOnReadinessGate:
    """CI gate: check_llm_on_readiness() must return all_passed=True."""

    def test_all_readiness_checks_pass(self):
        """The CI gate itself — blocks merge if any check fails."""
        result: ReadinessResult = check_llm_on_readiness()

        if not result.all_passed:
            fail_detail = "\n".join(
                f"  [{check_id}] {result.checks.get(check_id, '?')}"
                for check_id in result.checks
            )
            pytest.fail(
                f"LLM-On readiness gate FAILED with {len(result.failures)} failure(s):\n"
                + "\n".join(f"  - {f}" for f in result.failures)
                + f"\n\nFull check results:\n{fail_detail}"
            )

    def test_result_has_all_check_ids(self):
        """Every defined check must appear in the result."""
        result = check_llm_on_readiness()
        assert len(result.checks) >= 6, f"Expected >= 6 checks, got {len(result.checks)}"

    def test_readiness_result_fields(self):
        """ReadinessResult must be well-formed."""
        result = check_llm_on_readiness()
        assert isinstance(result.all_passed, bool)
        assert isinstance(result.failures, list)
        assert isinstance(result.checks, dict)
        for check_id, passed in result.checks.items():
            assert isinstance(check_id, str), f"check_id must be str, got {type(check_id)}"
            assert isinstance(passed, bool), f"check value must be bool, got {type(passed)}"

    def test_render_readiness_status(self):
        """render_readiness_status must produce JSON-safe output."""
        result = check_llm_on_readiness()
        status = render_readiness_status(result)

        assert isinstance(status, dict)
        assert status["status"] in ("READY", "NOT_READY")
        assert status["all_passed"] == result.all_passed
        assert isinstance(status["checks"], dict)
        assert isinstance(status["failures"], list)

    def test_readiness_is_deterministic(self):
        """Readiness result must be deterministic across calls."""
        r1 = check_llm_on_readiness()
        r2 = check_llm_on_readiness()
        assert r1.all_passed == r2.all_passed
        assert r1.checks == r2.checks
        assert r1.failures == r2.failures
