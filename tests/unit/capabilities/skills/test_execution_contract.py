"""
Tests for Phase 3.21.2 — Skill Execution Semantics
"""

from __future__ import annotations

import pytest

from src.capabilities.skills.execution_contract import (
    ATOMICITY_ALL_OR_NOTHING,
    ATOMICITY_BEST_EFFORT,
    ATOMICITY_CHECKPOINT,
    DEFAULT_SKILL_EXECUTION_CONTRACT,
    STEP_FAILURE_ABORT,
    STEP_FAILURE_CONTINUE,
    STEP_FAILURE_RETRY,
    STEP_FAILURE_SKIP,
    VALID_ATOMICITY_MODES,
    VALID_STEP_FAILURE_POLICIES,
    SkillCompensationStep,
    SkillExecutionContract,
    SkillRetryPolicy,
    SkillSideEffectBudget,
)


# ===========================================================================
# SkillRetryPolicy
# ===========================================================================

class TestSkillRetryPolicy:
    def test_defaults(self):
        p = SkillRetryPolicy()
        assert p.max_attempts == 3
        assert p.backoff_factor == 2.0
        assert p.retryable_error_types == ()

    def test_custom_values(self):
        p = SkillRetryPolicy(
            max_attempts=5,
            backoff_factor=1.5,
            retryable_error_types=("PrimitiveTimeout", "PrimitiveRetryableError"),
        )
        assert p.max_attempts == 5
        assert p.backoff_factor == 1.5
        assert "PrimitiveTimeout" in p.retryable_error_types

    def test_max_attempts_zero_raises(self):
        with pytest.raises(ValueError, match="max_attempts"):
            SkillRetryPolicy(max_attempts=0)

    def test_backoff_factor_below_one_raises(self):
        with pytest.raises(ValueError, match="backoff_factor"):
            SkillRetryPolicy(backoff_factor=0.5)

    def test_is_frozen(self):
        p = SkillRetryPolicy()
        with pytest.raises(Exception):
            p.max_attempts = 99  # type: ignore[misc]

    def test_max_attempts_one_means_no_retry(self):
        p = SkillRetryPolicy(max_attempts=1)
        assert p.max_attempts == 1

    def test_backoff_factor_one_is_valid(self):
        p = SkillRetryPolicy(backoff_factor=1.0)
        assert p.backoff_factor == 1.0


# ===========================================================================
# SkillCompensationStep
# ===========================================================================

class TestSkillCompensationStep:
    def test_construction(self):
        s = SkillCompensationStep(
            step_name="write_file", call="file_delete", args={"path": "/tmp/x"}
        )
        assert s.step_name == "write_file"
        assert s.call == "file_delete"
        assert s.args == {"path": "/tmp/x"}

    def test_empty_step_name_raises(self):
        with pytest.raises(ValueError, match="step_name"):
            SkillCompensationStep(step_name="", call="file_delete")

    def test_empty_call_raises(self):
        with pytest.raises(ValueError, match="call"):
            SkillCompensationStep(step_name="write_file", call="")

    def test_args_deep_copied(self):
        mutable = {"path": "/tmp/x"}
        s = SkillCompensationStep(step_name="s", call="c", args=mutable)
        mutable["path"] = "/changed"
        assert s.args["path"] == "/tmp/x"

    def test_is_frozen(self):
        s = SkillCompensationStep(step_name="s", call="c")
        with pytest.raises(Exception):
            s.call = "other"  # type: ignore[misc]


# ===========================================================================
# SkillSideEffectBudget
# ===========================================================================

class TestSkillSideEffectBudget:
    def test_defaults_are_unlimited(self):
        b = SkillSideEffectBudget()
        assert b.max_mutations == -1
        assert b.max_file_writes == -1
        assert b.max_network_calls == -1
        assert b.is_unlimited()

    def test_constrained_is_not_unlimited(self):
        b = SkillSideEffectBudget(max_file_writes=2)
        assert not b.is_unlimited()

    def test_invalid_negative_raises(self):
        with pytest.raises(ValueError, match="max_mutations"):
            SkillSideEffectBudget(max_mutations=-2)

    def test_zero_is_valid(self):
        b = SkillSideEffectBudget(max_mutations=0, max_file_writes=0, max_network_calls=0)
        assert b.max_mutations == 0
        assert not b.is_unlimited()

    def test_is_frozen(self):
        b = SkillSideEffectBudget()
        with pytest.raises(Exception):
            b.max_mutations = 5  # type: ignore[misc]


# ===========================================================================
# SkillExecutionContract construction
# ===========================================================================

class TestSkillExecutionContractConstruction:
    def test_defaults(self):
        c = SkillExecutionContract()
        assert c.timeout_seconds is None
        assert c.cancellable is False
        assert c.retry_policy is None
        assert c.atomicity == ATOMICITY_BEST_EFFORT
        assert c.compensation_steps == ()
        assert c.side_effect_budget is None
        assert c.step_failure_policy == STEP_FAILURE_ABORT
        assert c.allow_parallel_steps is False
        assert c.allow_step_skip is False

    def test_custom_contract(self):
        retry = SkillRetryPolicy(max_attempts=2)
        budget = SkillSideEffectBudget(max_file_writes=1)
        c = SkillExecutionContract(
            timeout_seconds=30.0,
            cancellable=True,
            retry_policy=retry,
            atomicity=ATOMICITY_CHECKPOINT,
            side_effect_budget=budget,
            step_failure_policy=STEP_FAILURE_CONTINUE,
            allow_parallel_steps=True,
        )
        assert c.timeout_seconds == 30.0
        assert c.cancellable is True
        assert c.retry_policy.max_attempts == 2
        assert c.atomicity == ATOMICITY_CHECKPOINT
        assert c.side_effect_budget.max_file_writes == 1
        assert c.step_failure_policy == STEP_FAILURE_CONTINUE
        assert c.allow_parallel_steps is True

    def test_is_frozen(self):
        c = SkillExecutionContract()
        with pytest.raises(Exception):
            c.cancellable = True  # type: ignore[misc]


# ===========================================================================
# SkillExecutionContract validation
# ===========================================================================

class TestSkillExecutionContractValidation:
    def test_zero_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout_seconds"):
            SkillExecutionContract(timeout_seconds=0.0)

    def test_negative_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout_seconds"):
            SkillExecutionContract(timeout_seconds=-5.0)

    def test_invalid_atomicity_raises(self):
        with pytest.raises(ValueError, match="atomicity"):
            SkillExecutionContract(atomicity="invalid")

    def test_invalid_step_failure_policy_raises(self):
        with pytest.raises(ValueError, match="step_failure_policy"):
            SkillExecutionContract(step_failure_policy="explode")

    def test_compensation_steps_require_all_or_nothing(self):
        comp = SkillCompensationStep(step_name="s", call="c")
        with pytest.raises(ValueError, match="compensation_steps"):
            SkillExecutionContract(
                atomicity=ATOMICITY_BEST_EFFORT,
                compensation_steps=(comp,),
            )

    def test_compensation_steps_valid_with_all_or_nothing(self):
        comp = SkillCompensationStep(step_name="s", call="c")
        c = SkillExecutionContract(
            atomicity=ATOMICITY_ALL_OR_NOTHING,
            compensation_steps=(comp,),
        )
        assert len(c.compensation_steps) == 1

    def test_allow_step_skip_incompatible_with_all_or_nothing(self):
        with pytest.raises(ValueError, match="allow_step_skip"):
            SkillExecutionContract(
                atomicity=ATOMICITY_ALL_OR_NOTHING,
                allow_step_skip=True,
            )

    @pytest.mark.parametrize("atomicity", sorted(VALID_ATOMICITY_MODES))
    def test_all_atomicity_modes_accepted(self, atomicity):
        c = SkillExecutionContract(atomicity=atomicity)
        assert c.atomicity == atomicity

    @pytest.mark.parametrize("policy", sorted(VALID_STEP_FAILURE_POLICIES))
    def test_all_step_failure_policies_accepted(self, policy):
        c = SkillExecutionContract(step_failure_policy=policy)
        assert c.step_failure_policy == policy


# ===========================================================================
# SkillExecutionContract.from_dict
# ===========================================================================

class TestSkillExecutionContractFromDict:
    def test_empty_dict_uses_defaults(self):
        c = SkillExecutionContract.from_dict({})
        assert c.timeout_seconds is None
        assert c.cancellable is False
        assert c.retry_policy is None
        assert c.atomicity == ATOMICITY_BEST_EFFORT

    def test_full_dict(self):
        data = {
            "timeout_seconds": 60.0,
            "cancellable": True,
            "retry_policy": {
                "max_attempts": 4,
                "backoff_factor": 1.5,
                "retryable_error_types": ["PrimitiveTimeout"],
            },
            "atomicity": "checkpoint",
            "side_effect_budget": {
                "max_mutations": 10,
                "max_file_writes": 5,
                "max_network_calls": 3,
            },
            "step_failure_policy": "continue",
            "allow_parallel_steps": True,
            "allow_step_skip": True,
        }
        c = SkillExecutionContract.from_dict(data)
        assert c.timeout_seconds == 60.0
        assert c.cancellable is True
        assert c.retry_policy.max_attempts == 4
        assert c.retry_policy.backoff_factor == 1.5
        assert "PrimitiveTimeout" in c.retry_policy.retryable_error_types
        assert c.atomicity == ATOMICITY_CHECKPOINT
        assert c.side_effect_budget.max_file_writes == 5
        assert c.step_failure_policy == STEP_FAILURE_CONTINUE
        assert c.allow_parallel_steps is True
        assert c.allow_step_skip is True

    def test_compensation_steps_parsed(self):
        data = {
            "atomicity": "all_or_nothing",
            "compensation_steps": [
                {"step_name": "write_db", "call": "db_delete", "args": {"id": "1"}},
            ],
        }
        c = SkillExecutionContract.from_dict(data)
        assert len(c.compensation_steps) == 1
        assert c.compensation_steps[0].step_name == "write_db"
        assert c.compensation_steps[0].call == "db_delete"

    def test_partial_retry_dict_uses_defaults(self):
        c = SkillExecutionContract.from_dict({"retry_policy": {"max_attempts": 2}})
        assert c.retry_policy.max_attempts == 2
        assert c.retry_policy.backoff_factor == 2.0


# ===========================================================================
# DEFAULT_SKILL_EXECUTION_CONTRACT
# ===========================================================================

class TestDefaultSkillExecutionContract:
    def test_is_instance(self):
        assert isinstance(DEFAULT_SKILL_EXECUTION_CONTRACT, SkillExecutionContract)

    def test_safe_defaults(self):
        d = DEFAULT_SKILL_EXECUTION_CONTRACT
        assert d.timeout_seconds is None
        assert d.cancellable is False
        assert d.retry_policy is None
        assert d.atomicity == ATOMICITY_BEST_EFFORT
        assert d.step_failure_policy == STEP_FAILURE_ABORT
        assert d.allow_parallel_steps is False
        assert d.allow_step_skip is False


# ===========================================================================
# CapabilitySkill integration
# ===========================================================================

class TestCapabilitySkillExecutionContractIntegration:
    """
    Verify execution_contract is wired into CapabilitySkill correctly.
    """

    def _make_skill(self, contract_dict=None):
        from unittest.mock import MagicMock
        from src.capabilities.skills.skill import CapabilitySkill
        from src.capabilities.skills.manifest import SkillManifest

        manifest = SkillManifest(
            name="test.skill",
            description="Test skill",
            primitives=[],
            inputs={},
            steps=[],
            execution_contract=contract_dict,
        )
        registry = MagicMock()
        registry.get.return_value = None
        return CapabilitySkill.from_manifest(manifest, registry)

    def test_no_contract_dict_gives_none(self):
        skill = self._make_skill(contract_dict=None)
        assert skill.execution_contract is None

    def test_contract_dict_parsed_to_contract(self):
        skill = self._make_skill(
            contract_dict={"timeout_seconds": 10.0, "cancellable": True}
        )
        assert isinstance(skill.execution_contract, SkillExecutionContract)
        assert skill.execution_contract.timeout_seconds == 10.0
        assert skill.execution_contract.cancellable is True

    def test_default_field_is_none(self):
        from src.capabilities.skills.skill import CapabilitySkill
        from src.capabilities.skills.manifest import SkillManifest
        manifest = SkillManifest(name="x", description="x")
        skill = CapabilitySkill(
            manifest=manifest,
            primitives={},
            input_schema={},
            output_schema={},
        )
        assert skill.execution_contract is None
