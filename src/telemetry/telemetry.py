import time
from collections import defaultdict

class Telemetry:
    """
    MVP: in-memory counters + timings for core loop events.
    """

    def __init__(self):
        self.counters = defaultdict(int)
        self.timings = defaultdict(list)

    def inc(self, name: str, amount: int = 1):
        self.counters[name] += amount

    def time(self, name: str):
        """
        Context manager for timing blocks.
        Usage:
            with telemetry.time("llm_latency"):
                ...
        """
        class Timer:
            def __enter__(inner_self):
                inner_self.start = time.time()

            def __exit__(inner_self, exc_type, exc, tb):
                duration = time.time() - inner_self.start
                self.timings[name].append(duration)

        return Timer()

    def snapshot(self):
        """
        Return a structured snapshot of all metrics.
        """
        return {
            "counters": dict(self.counters),
            "timings": {k: sum(v) / len(v) if v else 0 for k, v in self.timings.items()},
        }