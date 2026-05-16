import json
from datetime import datetime

from src.observability.logger import Logger, StdoutLogger, StructuredLogger


def test_logger_is_abstract():
    assert hasattr(Logger, "__abstractmethods__")
    assert "log" in Logger.__abstractmethods__


def test_stdout_logger_emits_single_json_line(capsys):
    logger = StdoutLogger()

    logger.log("event.test", {"x": 1})

    captured = capsys.readouterr().out.strip()
    payload = json.loads(captured)
    assert payload["event"] == "event.test"
    assert payload["payload"] == {"x": 1}
    assert isinstance(payload["timestamp"], str)
    datetime.fromisoformat(payload["timestamp"])


def test_structured_logger_delegates_to_sink():
    class FakeSink:
        def __init__(self):
            self.calls = []

        def log(self, event: str, payload: dict) -> None:
            self.calls.append((event, payload))

    sink = FakeSink()
    logger = StructuredLogger(sink=sink)

    logger.core("core.event", {"a": 1})
    logger.governance("gov.event", {"b": 2})
    logger.execution("exec.event", {"c": 3})
    logger.policy("policy.event", {"d": 4})

    assert sink.calls == [
        ("core.event", {"a": 1}),
        ("gov.event", {"b": 2}),
        ("exec.event", {"c": 3}),
        ("policy.event", {"d": 4}),
    ]
