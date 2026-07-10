"""Backend token-bucket service independent of FastAPI and storage technology."""

import math
from collections.abc import Hashable, Mapping

from enterprise_ai.rate_limit.clock import Clock
from enterprise_ai.rate_limit.models import (
    RateLimitDecision,
    RateLimitHeaders,
    RateLimitPolicy,
    RateLimitPolicyName,
    RateLimitReasonCode,
    RateLimitRequest,
    RateLimitSubjectCategory,
)
from enterprise_ai.rate_limit.store import BucketStore, RateLimitStoreError


class RateLimitEnforcementError(RuntimeError):
    """Fail-closed error with no internal key or store details."""


class TokenBucketRateLimiter:
    def __init__(
        self,
        *,
        enabled: bool,
        policies: Mapping[RateLimitPolicyName, RateLimitPolicy],
        store: BucketStore,
        clock: Clock,
    ) -> None:
        self._enabled = enabled
        self._policies = policies
        self._store = store
        self._clock = clock

    async def evaluate(
        self,
        *,
        bucket_key: Hashable,
        policy_name: RateLimitPolicyName,
        request: RateLimitRequest,
    ) -> RateLimitDecision:
        policy = self._policies.get(policy_name)
        if policy is None or request.policy != policy or request.cost != policy.request_cost:
            raise RateLimitEnforcementError("rate-limit policy is invalid")
        if not self._enabled:
            return self._decision(
                allowed=True,
                policy=policy,
                request=request,
                remaining=policy.capacity,
                retry_after=None,
                reason=RateLimitReasonCode.DISABLED,
            )
        try:
            result = await self._store.consume(bucket_key, policy, request.cost, self._clock.now())
        except (RateLimitStoreError, ValueError) as error:
            raise RateLimitEnforcementError("rate-limit enforcement failed") from error
        return self._decision(
            allowed=result.allowed,
            policy=policy,
            request=request,
            remaining=result.remaining_tokens,
            retry_after=result.retry_after_seconds,
            reason=(
                RateLimitReasonCode.ALLOWED if result.allowed else RateLimitReasonCode.EXCEEDED
            ),
        )

    def request_for(
        self, policy_name: RateLimitPolicyName, subject: RateLimitSubjectCategory
    ) -> RateLimitRequest:
        policy = self._policies.get(policy_name)
        if policy is None:
            raise RateLimitEnforcementError("rate-limit policy is invalid")
        return RateLimitRequest(policy=policy, subject_category=subject, cost=policy.request_cost)

    @staticmethod
    def headers_for(decision: RateLimitDecision) -> RateLimitHeaders:
        reset = decision.retry_after_seconds or 0
        return RateLimitHeaders(
            limit=math.floor(decision.capacity),
            remaining=math.floor(decision.remaining_tokens + 1e-9),
            reset_after_seconds=max(0, reset),
            retry_after_seconds=decision.retry_after_seconds,
        )

    @staticmethod
    def _decision(
        *,
        allowed: bool,
        policy: RateLimitPolicy,
        request: RateLimitRequest,
        remaining: float,
        retry_after: int | None,
        reason: RateLimitReasonCode,
    ) -> RateLimitDecision:
        return RateLimitDecision(
            allowed=allowed,
            policy_name=policy.name,
            requested_cost=request.cost,
            remaining_tokens=max(0.0, min(policy.capacity, remaining)),
            capacity=policy.capacity,
            retry_after_seconds=retry_after,
            reason_code=reason,
            public_explanation=(
                "Request is allowed." if allowed else "Too many requests. Please try again later."
            ),
            subject_category=request.subject_category,
        )
