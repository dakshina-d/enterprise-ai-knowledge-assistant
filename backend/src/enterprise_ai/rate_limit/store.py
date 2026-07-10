"""Atomic async bucket storage abstraction and process-local implementation."""

import asyncio
import logging
import math
from collections.abc import Hashable
from typing import Protocol

from enterprise_ai.rate_limit.models import BucketState, RateLimitPolicy, StoreEvaluation

EPSILON = 1e-9
logger = logging.getLogger(__name__)


class RateLimitStoreError(RuntimeError):
    """Sanitized enforcement-store failure."""


class BucketStore(Protocol):
    async def consume(
        self,
        key: Hashable,
        policy: RateLimitPolicy,
        cost: float,
        now: float,
    ) -> StoreEvaluation:
        """Atomically refill and consume one bucket."""
        ...


class InMemoryBucketStore:
    """Process-local store using independent locks per bucket key."""

    def __init__(
        self, *, ttl_seconds: float, cleanup_interval: int = 64, cleanup_scan: int = 128
    ) -> None:
        if ttl_seconds <= 0 or cleanup_interval <= 0 or cleanup_scan <= 0:
            raise ValueError("store cleanup values must be positive")
        self._ttl_seconds = ttl_seconds
        self._cleanup_interval = cleanup_interval
        self._cleanup_scan = cleanup_scan
        self._states: dict[Hashable, BucketState] = {}
        self._locks: dict[Hashable, asyncio.Lock] = {}
        self._access_count = 0

    async def consume(
        self,
        key: Hashable,
        policy: RateLimitPolicy,
        cost: float,
        now: float,
    ) -> StoreEvaluation:
        if not math.isfinite(now) or not math.isfinite(cost) or cost <= 0:
            raise RateLimitStoreError("invalid rate-limit evaluation input")
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                state = self._states.get(key)
                if state is None:
                    state = BucketState(policy.capacity, now, now)
                self._validate_state(state, policy)
                elapsed = max(0.0, now - state.last_refill_monotonic)
                available = min(
                    policy.capacity,
                    state.available_tokens + elapsed * policy.refill_rate_per_second,
                )
                if available + EPSILON >= cost:
                    remaining = max(0.0, available - cost)
                    result = StoreEvaluation(True, remaining, None)
                else:
                    remaining = max(0.0, available)
                    retry = math.ceil((cost - remaining) / policy.refill_rate_per_second)
                    result = StoreEvaluation(False, remaining, max(0, retry))
                self._states[key] = BucketState(
                    available_tokens=remaining,
                    last_refill_monotonic=max(now, state.last_refill_monotonic),
                    last_seen_monotonic=max(now, state.last_seen_monotonic),
                )
        except asyncio.CancelledError:
            raise
        except RateLimitStoreError:
            raise
        except Exception as error:
            raise RateLimitStoreError("rate-limit store enforcement failed") from error

        self._access_count += 1
        if self._access_count % self._cleanup_interval == 0:
            try:
                self.cleanup(now)
            except Exception:
                logger.warning("rate_limit_cleanup_failed", extra={"outcome": "ignored"})
        return result

    def cleanup(self, now: float) -> int:
        """Opportunistically scan a bounded number of inactive, unlocked buckets."""
        removed = 0
        for key, state in list(self._states.items())[: self._cleanup_scan]:
            lock = self._locks.get(key)
            if now - state.last_seen_monotonic > self._ttl_seconds and not (lock and lock.locked()):
                self._states.pop(key, None)
                self._locks.pop(key, None)
                removed += 1
        return removed

    def bucket_count(self) -> int:
        """Return process-local count for tests and internal diagnostics only."""
        return len(self._states)

    @staticmethod
    def _validate_state(state: BucketState, policy: RateLimitPolicy) -> None:
        values = (
            state.available_tokens,
            state.last_refill_monotonic,
            state.last_seen_monotonic,
        )
        if not all(math.isfinite(value) for value in values):
            raise RateLimitStoreError("corrupted bucket state")
        if state.available_tokens < 0 or state.available_tokens > policy.capacity + EPSILON:
            raise RateLimitStoreError("corrupted bucket state")

    def inject_state_for_test(self, key: Hashable, state: BucketState) -> None:
        """Inject state exclusively for corruption-path tests."""
        self._states[key] = state
