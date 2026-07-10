"""Deterministic unit and concurrency tests for token-bucket limiting."""

import asyncio
import math

import pytest
from enterprise_ai.core.config import Settings
from enterprise_ai.rate_limit.clock import ManualClock
from enterprise_ai.rate_limit.models import (
    BucketState,
    RateLimitDecision,
    RateLimitPolicy,
    RateLimitPolicyName,
    RateLimitSubjectCategory,
)
from enterprise_ai.rate_limit.store import InMemoryBucketStore, RateLimitStoreError
from enterprise_ai.rate_limit.token_bucket import (
    RateLimitEnforcementError,
    TokenBucketRateLimiter,
)
from pydantic import ValidationError


def _limiter(
    *,
    capacity: float = 5.0,
    refill: float = 1.0,
    cost: float = 1.0,
    enabled: bool = True,
    clock: ManualClock | None = None,
    store: InMemoryBucketStore | None = None,
) -> tuple[TokenBucketRateLimiter, ManualClock, InMemoryBucketStore]:
    active_clock = clock or ManualClock()
    active_store = store or InMemoryBucketStore(ttl_seconds=60)
    policy = RateLimitPolicy(RateLimitPolicyName.STANDARD, capacity, refill, cost)
    return (
        TokenBucketRateLimiter(
            enabled=enabled,
            policies={RateLimitPolicyName.STANDARD: policy},
            store=active_store,
            clock=active_clock,
        ),
        active_clock,
        active_store,
    )


async def _evaluate(limiter: TokenBucketRateLimiter, key: str = "user:test") -> RateLimitDecision:
    policy_name = RateLimitPolicyName.STANDARD
    return await limiter.evaluate(
        bucket_key=key,
        policy_name=policy_name,
        request=limiter.request_for(policy_name, RateLimitSubjectCategory.AUTHENTICATED_USER),
    )


@pytest.mark.parametrize(
    "field",
    [
        "rate_limit_login_capacity",
        "rate_limit_login_refill_per_second",
        "rate_limit_login_cost",
        "rate_limit_standard_capacity",
        "rate_limit_standard_refill_per_second",
        "rate_limit_standard_cost",
        "rate_limit_expensive_capacity",
        "rate_limit_expensive_refill_per_second",
        "rate_limit_expensive_cost",
        "rate_limit_bucket_ttl_seconds",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_invalid_configuration_values_fail_fast(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_explicit_disabled_mode_returns_allowed_without_consumption() -> None:
    limiter, _, store = _limiter(enabled=False)
    decision = asyncio.run(_evaluate(limiter))
    assert decision.allowed
    assert decision.reason_code.value == "rate_limit.disabled"
    assert decision.remaining_tokens == decision.capacity
    assert store.bucket_count() == 0


def test_full_bucket_deduction_exact_boundary_and_multi_token_cost() -> None:
    limiter, _, _ = _limiter(capacity=4, refill=1, cost=2)
    first = asyncio.run(_evaluate(limiter))
    second = asyncio.run(_evaluate(limiter))
    denied = asyncio.run(_evaluate(limiter))

    assert first.allowed and first.remaining_tokens == 2
    assert second.allowed and second.remaining_tokens == 0
    assert not denied.allowed
    assert denied.remaining_tokens == 0
    assert denied.retry_after_seconds == 2


def test_fractional_refill_retry_and_capacity_cap() -> None:
    limiter, clock, _ = _limiter(capacity=2, refill=0.5, cost=1)
    assert asyncio.run(_evaluate(limiter)).allowed
    assert asyncio.run(_evaluate(limiter)).allowed
    denied = asyncio.run(_evaluate(limiter))
    assert denied.retry_after_seconds == 2

    clock.advance(1)
    half = asyncio.run(_evaluate(limiter))
    assert not half.allowed and half.remaining_tokens == pytest.approx(0.5)
    clock.advance(1)
    exact = asyncio.run(_evaluate(limiter))
    assert exact.allowed and exact.remaining_tokens == pytest.approx(0.0)
    clock.advance(100)
    capped = asyncio.run(_evaluate(limiter))
    assert capped.allowed and capped.remaining_tokens == pytest.approx(1.0)


def test_negative_elapsed_time_does_not_corrupt_bucket() -> None:
    clock = ManualClock(10)
    limiter, _, _ = _limiter(capacity=2, refill=1, clock=clock)
    assert asyncio.run(_evaluate(limiter)).remaining_tokens == 1
    clock.set(5)
    decision = asyncio.run(_evaluate(limiter))
    assert decision.allowed and decision.remaining_tokens == 0
    assert decision.remaining_tokens >= 0


def test_corrupted_bucket_state_fails_closed() -> None:
    store = InMemoryBucketStore(ttl_seconds=60)
    store.inject_state_for_test("user:test", BucketState(math.nan, 0, 0))
    limiter, _, _ = _limiter(store=store)
    with pytest.raises(RateLimitEnforcementError):
        asyncio.run(_evaluate(limiter))


def test_unknown_or_client_modified_policy_fails_closed() -> None:
    limiter, _, _ = _limiter()
    with pytest.raises(RateLimitEnforcementError):
        limiter.request_for(RateLimitPolicyName.LOGIN, RateLimitSubjectCategory.ANONYMOUS)


def test_concurrent_requests_cannot_overspend_or_deadlock() -> None:
    limiter, _, _ = _limiter(capacity=10, refill=0.01)

    async def scenario() -> list[bool]:
        decisions = await asyncio.wait_for(
            asyncio.gather(*(_evaluate(limiter) for _ in range(50))), timeout=2
        )
        return [decision.allowed for decision in decisions]

    allowed = asyncio.run(scenario())
    assert sum(allowed) == 10


def test_different_users_and_login_keys_are_isolated() -> None:
    limiter, _, _ = _limiter(capacity=1, refill=0.01)

    async def scenario() -> tuple[bool, bool, bool, bool]:
        viewer, analyst = await asyncio.gather(
            _evaluate(limiter, "user:viewer"), _evaluate(limiter, "user:analyst")
        )
        login, viewer_again = await asyncio.gather(
            _evaluate(limiter, "anonymous:digest"), _evaluate(limiter, "user:viewer")
        )
        return viewer.allowed, analyst.allowed, login.allowed, viewer_again.allowed

    assert asyncio.run(scenario()) == (True, True, True, False)


def test_opportunistic_cleanup_removes_state_and_lock() -> None:
    clock = ManualClock()
    store = InMemoryBucketStore(ttl_seconds=10, cleanup_interval=1)
    limiter, _, _ = _limiter(clock=clock, store=store)
    asyncio.run(_evaluate(limiter, "stale"))
    assert store.bucket_count() == 1
    clock.advance(11)
    asyncio.run(_evaluate(limiter, "current"))
    assert store.bucket_count() == 1


def test_invalid_store_inputs_are_rejected() -> None:
    store = InMemoryBucketStore(ttl_seconds=10)
    policy = RateLimitPolicy(RateLimitPolicyName.STANDARD, 1, 1, 1)
    with pytest.raises(RateLimitStoreError):
        asyncio.run(store.consume("key", policy, -1, 0))
