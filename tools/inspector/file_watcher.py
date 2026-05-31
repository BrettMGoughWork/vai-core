"""
TraceDirectoryWatcher — polls a directory for new/modified cycle JSON files.

Never crashes the dashboard on malformed input.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Dict


class TraceDirectoryWatcher:
    """
    Polls *path* every call to poll() for new or modified ``cycle_*.json`` files.

    Calls ``callback(filename, parsed_dict)`` for each new or modified file.
    Designed to be driven by Textual's ``set_interval`` timer.
    """

    def __init__(self, path: Path, callback: Callable[[str, dict], None]) -> None:
        self._path = path
        self._callback = callback
        self._seen: Dict[str, float] = {}  # filename → mtime

    def poll(self) -> None:
        """Check for new or modified JSON files and invoke callback for each."""
        if not self._path.exists():
            return

        try:
            candidates = sorted(self._path.glob("cycle_*.json"))
        except OSError:
            return

        for file in candidates:
            try:
                mtime = file.stat().st_mtime
            except OSError:
                continue

            prev_mtime = self._seen.get(file.name)
            if prev_mtime is not None and abs(prev_mtime - mtime) < 1e-6:
                continue  # unchanged

            self._seen[file.name] = mtime
            data = _safe_load(file)
            if data is not None:
                self._callback(file.name, data)

    @property
    def watched_path(self) -> Path:
        return self._path


def _safe_load(path: Path) -> dict | None:
    """Load and parse a JSON file. Returns None on any error."""
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        pass
    return None
