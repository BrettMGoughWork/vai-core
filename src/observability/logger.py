from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
from typing import Any


class Logger(ABC):
    @abstractmethod
    def log(self, event: str, payload: dict) -> None:
        pass


class StdoutLogger(Logger):
    def log(self, event: str, payload: dict) -> None:
        record = {
            "event": event,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(record, ensure_ascii=False), flush=True)


class StructuredLogger(Logger):
    """
    Backward-compatible facade preserving existing call sites.
    """

    def __init__(self, sink: Logger | None = None):
        self.sink = sink or StdoutLogger()

    def log(self, event: str, payload: dict) -> None:
        self.sink.log(event, payload)

    def core(self, event: str, payload: dict[str, Any]) -> None:
        self.log(event, payload)

    def governance(self, event: str, payload: dict[str, Any]) -> None:
        self.log(event, payload)

    def execution(self, event: str, payload: dict[str, Any]) -> None:
        self.log(event, payload)

    def policy(self, event: str, payload: dict[str, Any]) -> None:
        self.log(event, payload)