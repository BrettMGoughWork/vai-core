"""Minimal file-based diagnostic logging.

Writes timestamped, thread-safe messages to a temp file so we can trace
the exact failure path in the parallelize() council flow without relying
on stderr (which may be buffered or redirected differently in daemon threads).
"""

from __future__ import annotations

import os
import threading
import time

_LOG_PATH = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    "vai_diag.log",
)
_lock = threading.Lock()


def diag(msg: str) -> None:
    """Append a diagnostic line with timestamp + thread ID."""
    ts = time.strftime("%H:%M:%S", time.gmtime())
    tid = threading.get_ident()
    with _lock:
        with open(_LOG_PATH, "a") as f:
            f.write(f"[{ts} t:{tid}] {msg}\n")
