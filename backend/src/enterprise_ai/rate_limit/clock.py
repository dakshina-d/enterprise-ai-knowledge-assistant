"""Injectable monotonic clocks for production and deterministic tests."""

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Return monotonic seconds from an arbitrary origin."""
        ...


class MonotonicClock:
    def now(self) -> float:
        return time.monotonic()


class ManualClock:
    """Explicitly advanced monotonic clock intended for tests."""

    def __init__(self, initial: float = 0.0) -> None:
        self._value = initial

    def now(self) -> float:
        return self._value

    def advance(self, seconds: float) -> None:
        self._value += seconds

    def set(self, value: float) -> None:
        self._value = value
