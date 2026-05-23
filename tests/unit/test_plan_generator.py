import pytest

from src.core.planning.plan_generator import PlanGenerator, PlanPrompt
from src.core.types.step_state import StepState, StepStatus
from src.core.types.errors.ValidationError import ValidationError

FAKE_CAPABILITIES = {
    "echo": {
        "name": "echo",
        "version": "1.0",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"}
            },
            "required": ["text"]
        }
    }
}

def make_state(**overrides):
    """
    Minimal deterministic StepState factory.
    Mirrors your existing test helpers.
    """
    base = StepState(
        step_id="test-step",
        status=StepStatus.PENDING,
        cognitive_input={
            "mode": "plan",
            "user_request": "test request",
            "memory": {},
        },
        last_result=None,
        trace=[],
        created_at=0,
    )
    inst = base.replace(**overrides)
    object.__setattr__(inst, "capabilities_hash", "dummyhash")
    object.__setattr__(inst, "state_hash", "dummyhash")
    return inst


def test_plan_generator_rejects_forbidden_fields(monkeypatch):
    """
    Inject a forbidden field into the raw prompt dict and ensure
    the validator catches it.
    """
    gen = PlanGenerator(capabilities=FAKE_CAPABILITIES)
    state = make_state()

    # Monkeypatch _build_prompt_dict to inject a forbidden field
    def bad_build(_state):
        return {
            "prompt": "x",
            "metadata": {"version": "1"},
            "llm_config": {"temperature": 0.9}, # forbidden
        }

    monkeypatch.setattr(gen, "_build_prompt_dict", bad_build)

    with pytest.raises(ValidationError):
        gen.generate(state)


def test_plan_generator_purity_enforced(monkeypatch):
    """
    Ensure purity enforcement is applied after normalisation.
    """
    gen = PlanGenerator(capabilities=FAKE_CAPABILITIES)
    state = make_state()

    # Inject a non‑pure value
    def bad_build(_state):
        return {
            "prompt": "x",
            "metadata": {"version": "1"},
            "non_pure": object(), # not JSON‑serialisable
        }

    monkeypatch.setattr(gen, "_build_prompt_dict", bad_build)

    with pytest.raises(ValidationError):
        gen.generate(state)