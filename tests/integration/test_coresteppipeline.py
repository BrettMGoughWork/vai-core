from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROOT_STR = str(ROOT)
if ROOT_STR not in sys.path:
    sys.path.insert(0, ROOT_STR)

from src.core.loop import CoreStep
from src.core.planning.local_planner import LocalPlanner
from src.core.planning.plan_validator import PlanValidationError, PlanValidator
from src.execution.singleskillexecutor import SingleSkillExecutor
from src.observability.logger import StdoutLogger
from src.skills.skill_filter import SkillFilter
from src.skills.skill_ranker import SkillRanker

import src.core.loop as loop_module
import src.execution.singleskillexecutor as executor_module


@dataclass
class FakeMetadata:
    domains: list[str]
    cost_hint: int = 0
    latency_hint: int = 0


class FakeSkill:
    def __init__(
        self,
        skill_id: str,
        domains: list[str],
        schema: dict,
        output_schema: dict,
        execute_behavior=None,
    ):
        self.id = skill_id
        self.metadata = FakeMetadata(domains=domains, cost_hint=1, latency_hint=1)
        self.schema = schema
        self.input_schema = schema
        self.output_schema = output_schema
        self._execute_behavior = execute_behavior or (lambda _args: {"result": "ok"})

    def execute(self, args: dict) -> dict:
        return self._execute_behavior(args)


class FakeRegistry:
    _skills: dict[str, FakeSkill] = {}

    @classmethod
    def set_skills(cls, skills: list[FakeSkill]) -> None:
        cls._skills = {skill.id: skill for skill in skills}

    @classmethod
    def get(cls, name: str) -> FakeSkill:
        return cls._skills[name]


def _wire_fake_registry(monkeypatch: pytest.MonkeyPatch, skills: list[FakeSkill]) -> None:
    FakeRegistry.set_skills(skills)
    monkeypatch.setattr(loop_module, "SkillRegistry", FakeRegistry)
    monkeypatch.setattr(executor_module, "SkillRegistry", FakeRegistry)


def _build_core_step(planner=None) -> CoreStep:
    return CoreStep(
        skill_filter=SkillFilter(),
        skill_ranker=SkillRanker(),
        planner=planner or LocalPlanner(),
        plan_validator=PlanValidator(),
        executor=SingleSkillExecutor(),
    )


def test_core_step_happy_path(monkeypatch: pytest.MonkeyPatch):
    skill = FakeSkill(
        skill_id="math_add",
        domains=["math"],
        schema={"type": "object", "properties": {}, "required": []},
        output_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        },
    )
    _wire_fake_registry(monkeypatch, [skill])
    core_step = _build_core_step()
    state = {"skills": [skill]}

    updated = core_step.run("please do math", state)

    assert updated["lastusermessage"] == "please do math"
    assert updated["last_plan"].targetskillid == "math_add"
    assert updated["lastexecutionresult"].status == "success"
    assert updated["lastexecutionresult"].output == {"result": "ok"}
    assert "last_error" not in updated


def test_core_step_planner_error(monkeypatch: pytest.MonkeyPatch):
    class BrokenPlanner:
        def plan(self, _user_message, _ranked):
            raise RuntimeError("planner failed")

    skill = FakeSkill(
        skill_id="math_add",
        domains=["math"],
        schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {}, "required": []},
    )
    _wire_fake_registry(monkeypatch, [skill])
    core_step = _build_core_step(planner=BrokenPlanner())
    state = {"skills": [skill]}

    updated = core_step.run("please do math", state)

    assert isinstance(updated["last_error"], RuntimeError)
    assert str(updated["last_error"]) == "planner failed"
    assert "last_plan" not in updated
    assert "lastexecutionresult" not in updated


def test_core_step_validator_error(monkeypatch: pytest.MonkeyPatch):
    skill = FakeSkill(
        skill_id="math_add",
        domains=["math"],
        schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        output_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        },
    )
    _wire_fake_registry(monkeypatch, [skill])
    core_step = _build_core_step()
    state = {"skills": [skill]}

    updated = core_step.run("please do math", state)

    assert isinstance(updated["last_error"], PlanValidationError)
    assert "Plan arguments do not match skill input schema" in str(updated["last_error"])
    assert "lastexecutionresult" not in updated


def test_core_step_executor_error(monkeypatch: pytest.MonkeyPatch):
    skill = FakeSkill(
        skill_id="math_add",
        domains=["math"],
        schema={"type": "object", "properties": {}, "required": []},
        output_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        },
        execute_behavior=lambda _args: (_ for _ in ()).throw(RuntimeError("execute failed")),
    )
    _wire_fake_registry(monkeypatch, [skill])
    core_step = _build_core_step()
    state = {"skills": [skill]}

    updated = core_step.run("please do math", state)

    assert updated["lastexecutionresult"].status == "error"
    assert str(updated["lastexecutionresult"].error) == "execute failed"
    assert "last_error" not in updated


def test_core_step_logging_integration(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    class LoggingCoreStep(CoreStep):
        def __init__(self, *args, logger: StdoutLogger, **kwargs):
            super().__init__(*args, **kwargs)
            self._logger = logger

        def _log(self, event: str, payload) -> None:
            self._logger.log(event, {"value": repr(payload)})

    skill = FakeSkill(
        skill_id="math_add",
        domains=["math"],
        schema={"type": "object", "properties": {}, "required": []},
        output_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        },
    )
    _wire_fake_registry(monkeypatch, [skill])
    core_step = LoggingCoreStep(
        skill_filter=SkillFilter(),
        skill_ranker=SkillRanker(),
        planner=LocalPlanner(),
        plan_validator=PlanValidator(),
        executor=SingleSkillExecutor(),
        logger=StdoutLogger(),
    )
    state = {"skills": [skill]}

    updated = core_step.run("please do math", state)
    assert updated["lastexecutionresult"].status == "success"

    output_lines = [line for line in capsys.readouterr().out.strip().splitlines() if line]
    assert len(output_lines) == 5

    events = []
    for line in output_lines:
        record = json.loads(line)
        events.append(record["event"])
        assert isinstance(record["payload"], dict)
        assert isinstance(record["timestamp"], str)
        datetime.fromisoformat(record["timestamp"])

    assert events == ["filtered", "ranked", "plan", "validated_plan", "execution_result"]
