"""Centralized rate-limit policy construction from validated settings."""

from types import MappingProxyType

from enterprise_ai.core.config import Settings
from enterprise_ai.rate_limit.models import RateLimitPolicy, RateLimitPolicyName


def policies_from_settings(
    settings: Settings,
) -> MappingProxyType[RateLimitPolicyName, RateLimitPolicy]:
    return MappingProxyType(
        {
            RateLimitPolicyName.LOGIN: RateLimitPolicy(
                RateLimitPolicyName.LOGIN,
                settings.rate_limit_login_capacity,
                settings.rate_limit_login_refill_per_second,
                settings.rate_limit_login_cost,
            ),
            RateLimitPolicyName.STANDARD: RateLimitPolicy(
                RateLimitPolicyName.STANDARD,
                settings.rate_limit_standard_capacity,
                settings.rate_limit_standard_refill_per_second,
                settings.rate_limit_standard_cost,
            ),
            RateLimitPolicyName.EXPENSIVE: RateLimitPolicy(
                RateLimitPolicyName.EXPENSIVE,
                settings.rate_limit_expensive_capacity,
                settings.rate_limit_expensive_refill_per_second,
                settings.rate_limit_expensive_cost,
            ),
        }
    )
