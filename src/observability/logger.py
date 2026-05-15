import logging
import json
import sys

# ANSI colours
RESET = "\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"

class StructuredLogger:
    """
    MVP: structured, colourised logs for core loop events.
    """

    def __init__(self, name="vai-core"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))

        self.logger.handlers = [handler]

    def _emit(self, colour, event, payload):
        msg = {
            "event": event,
            "payload": payload,
        }
        line = colour + json.dumps(msg, ensure_ascii=False) + RESET
        self.logger.info(line)

    def core(self, event, payload):
        self._emit(CYAN, event, payload)

    def governance(self, event, payload):
        self._emit(GREEN, event, payload)

    def execution(self, event, payload):
        self._emit(YELLOW, event, payload)

    def policy(self, event, payload):
        self._emit(MAGENTA, event, payload)