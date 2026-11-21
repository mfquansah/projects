"""Counts Claude usage (calls and tokens) so a batch can report what it cost. Thread-safe; never raises."""
from __future__ import annotations

import threading


class UsageMeter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += int(input_tokens or 0)
            self.output_tokens += int(output_tokens or 0)

    def snapshot(self) -> dict:
        with self._lock:
            return {"calls": self.calls, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


def record_message(meter: UsageMeter | None, msg) -> None:
    """Record one API reply's usage. Tolerates replies without usage info (still counts the call)."""
    if meter is None:
        return
    usage = getattr(msg, "usage", None)
    meter.add(getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)
