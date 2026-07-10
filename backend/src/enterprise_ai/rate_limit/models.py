"""Immutable public and internal token-bucket contracts."""

import math
from dataclasses import dataclass
from enum import StrEnum


class RateLimitPolicyName(StrEnum):
    LOGIN = "login"
    STANDARD = "standard"
    EXPENSIVE = "expensive"


class RateLimitReasonCode(StrEnum):
    ALLOWED = "rate_limit.allowed"
    DISABLED = "rate_limit.disabled"
    EXCEEDED = "rate_limit.exceeded"
    ENFORCEMENT_FAILED = "rate_limit.enforcement_failed"


class RateLimitSubjectCategory(StrEnum):
    ANONYMOUS = "anonymous"
    AUTHENTICATED_USER = "authenticated_user"


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    name: RateLimitPolicyName
    capacity: float
    refill_rate_per_second: float
    request_cost: float

    def __post_init__(self) -> None:
        values = (self.capacity, self.refill_rate_per_second, self.request_cost)
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError("rate-limit policy values must be positive")


@dataclass(frozen=True, slots=True)
class BucketState:
    available_tokens: float
    last_refill_monotonic: float
    last_seen_monotonic: float


@dataclass(frozen=True, slots=True)
class RateLimitRequest:
    policy: RateLimitPolicy
    subject_category: RateLimitSubjectCategory
    cost: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.cost) or self.cost <= 0:
            raise ValueError("request cost must be positive")


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    policy_name: RateLimitPolicyName
    requested_cost: float
    remaining_tokens: float
    capacity: float
    retry_after_seconds: int | None
    reason_code: RateLimitReasonCode
    public_explanation: str
    subject_category: RateLimitSubjectCategory


@dataclass(frozen=True, slots=True)
class RateLimitHeaders:
    limit: int
    remaining: int
    reset_after_seconds: int
    retry_after_seconds: int | None = None

    def as_http_headers(self) -> dict[str, str]:
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset_after_seconds),
        }
        if self.retry_after_seconds is not None:
            headers["Retry-After"] = str(self.retry_after_seconds)
        return headers


@dataclass(frozen=True, slots=True)
class StoreEvaluation:
    allowed: bool
    remaining_tokens: float
    retry_after_seconds: int | None
