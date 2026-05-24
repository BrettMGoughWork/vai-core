from src.core.planning.models.plan import Plan
from src.execution.singleskillexecutor import SingleSkillExecutor


class FakeSkill:
    def __init__(self):
        self.input_schema = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }
        self.output_schema = {
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        }

    def execute(self, args: dict) -> dict:
        return {"result": args["text"].upper()}


def test_execute_returns_success_for_valid_plan(monkeypatch):
    skill = FakeSkill()
    monkeypatch.setattr(
        "src.execution.singleskillexecutor.SkillRegistry.get",
        lambda _skill_id: skill,
    )
    executor = SingleSkillExecutor()
    plan = Plan(
        intent="echo",
        targetskillid="fake_echo",
        arguments={"text": "hi"},
        reasoning_summary="picked fake_echo",
    )

    result = executor.execute(plan)

    assert result.status == "success"
    assert result.output == {"result": "HI"}
    assert result.error is None
    assert result.skill_id == "fake_echo"
    assert result.raw_response == {"result": "HI"}


def test_execute_returns_error_when_input_validation_fails(monkeypatch):
    skill = FakeSkill()
    monkeypatch.setattr(
        "src.execution.singleskillexecutor.SkillRegistry.get",
        lambda _skill_id: skill,
    )
    executor = SingleSkillExecutor()
    plan = Plan(
        intent="echo",
        targetskillid="fake_echo",
        arguments={},
        reasoning_summary="picked fake_echo",
    )

    result = executor.execute(plan)

    assert result.status == "error"
    assert result.output is None
    assert result.error is not None
    assert result.skill_id == "fake_echo"


def test_execute_returns_error_when_skill_execution_raises(monkeypatch):
    skill = FakeSkill()

    def broken_execute(_args: dict) -> dict:
        raise RuntimeError("boom")

    skill.execute = broken_execute
    monkeypatch.setattr(
        "src.execution.singleskillexecutor.SkillRegistry.get",
        lambda _skill_id: skill,
    )
    executor = SingleSkillExecutor()
    plan = Plan(
        intent="echo",
        targetskillid="fake_echo",
        arguments={"text": "hi"},
        reasoning_summary="picked fake_echo",
    )

    result = executor.execute(plan)

    assert result.status == "error"
    assert result.output is None
    assert str(result.error) == "boom"
    assert result.raw_response is None


def test_execute_returns_error_when_output_fails_schema(monkeypatch):
    skill = FakeSkill()
    skill.execute = lambda _args: {"wrong": "shape"}
    monkeypatch.setattr(
        "src.execution.singleskillexecutor.SkillRegistry.get",
        lambda _skill_id: skill,
    )
    executor = SingleSkillExecutor()
    plan = Plan(
        intent="echo",
        targetskillid="fake_echo",
        arguments={"text": "hi"},
        reasoning_summary="picked fake_echo",
    )

    result = executor.execute(plan)

    assert result.status == "error"
    assert result.output is None
    assert result.error is not None
    assert result.raw_response == {"wrong": "shape"}
