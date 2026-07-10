"""FastAPI integration, safe identities, and fixed-policy dependencies."""

import hashlib
import ipaddress
from typing import Annotated, cast

from fastapi import Depends, Request, Response

from enterprise_ai.api.dependencies import CurrentPrincipal
from enterprise_ai.core.config import Settings
from enterprise_ai.models.identity import AuthenticatedPrincipal
from enterprise_ai.rate_limit.models import (
    RateLimitDecision,
    RateLimitPolicyName,
    RateLimitSubjectCategory,
)
from enterprise_ai.rate_limit.token_bucket import (
    RateLimitEnforcementError,
    TokenBucketRateLimiter,
)


class RateLimitExceededError(Exception):
    def __init__(self, decision: RateLimitDecision) -> None:
        super().__init__(decision.public_explanation)
        self.decision = decision


class RateLimitUnavailableError(Exception):
    """Fail-closed sanitized enforcement failure."""


def get_rate_limiter(request: Request) -> TokenBucketRateLimiter:
    return cast(TokenBucketRateLimiter, request.app.state.rate_limiter)


def get_rate_limit_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def anonymous_fingerprint(request: Request, settings: Settings) -> str:
    """Hash a conservatively selected network identity for login buckets."""
    direct_host = request.client.host if request.client else "unknown-client"
    value = direct_host
    trusted_hosts = {
        host.strip() for host in settings.trusted_proxy_hosts.split(",") if host.strip()
    }
    if settings.trust_proxy_headers and direct_host in trusted_hosts:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded is not None:
            if "," in forwarded:
                raise RateLimitUnavailableError("malformed forwarded client address")
            try:
                value = str(ipaddress.ip_address(forwarded.strip()))
            except ValueError as error:
                raise RateLimitUnavailableError("malformed forwarded client address") from error
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def enforce_login_rate_limit(
    request: Request,
    response: Response,
    limiter: Annotated[TokenBucketRateLimiter, Depends(get_rate_limiter)],
    settings: Annotated[Settings, Depends(get_rate_limit_settings)],
) -> RateLimitDecision:
    fingerprint = anonymous_fingerprint(request, settings)
    return await _enforce(
        limiter=limiter,
        bucket_key=f"anonymous:{fingerprint}",
        policy_name=RateLimitPolicyName.LOGIN,
        subject=RateLimitSubjectCategory.ANONYMOUS,
        response=response,
    )


async def enforce_standard_rate_limit(
    principal: CurrentPrincipal,
    response: Response,
    limiter: Annotated[TokenBucketRateLimiter, Depends(get_rate_limiter)],
) -> AuthenticatedPrincipal:
    await _enforce(
        limiter=limiter,
        bucket_key=f"user:{principal.identity.user_id}",
        policy_name=RateLimitPolicyName.STANDARD,
        subject=RateLimitSubjectCategory.AUTHENTICATED_USER,
        response=response,
    )
    return principal


async def enforce_expensive_rate_limit(
    principal: CurrentPrincipal,
    response: Response,
    limiter: Annotated[TokenBucketRateLimiter, Depends(get_rate_limiter)],
) -> AuthenticatedPrincipal:
    """Reusable future dependency; intentionally unattached to unfinished AI routes."""
    await _enforce(
        limiter=limiter,
        bucket_key=f"user:{principal.identity.user_id}:expensive",
        policy_name=RateLimitPolicyName.EXPENSIVE,
        subject=RateLimitSubjectCategory.AUTHENTICATED_USER,
        response=response,
    )
    return principal


RateLimitedPrincipal = Annotated[AuthenticatedPrincipal, Depends(enforce_standard_rate_limit)]


async def _enforce(
    *,
    limiter: TokenBucketRateLimiter,
    bucket_key: str,
    policy_name: RateLimitPolicyName,
    subject: RateLimitSubjectCategory,
    response: Response,
) -> RateLimitDecision:
    try:
        decision = await limiter.evaluate(
            bucket_key=bucket_key,
            policy_name=policy_name,
            request=limiter.request_for(policy_name, subject),
        )
    except RateLimitEnforcementError as error:
        raise RateLimitUnavailableError("rate-limit enforcement unavailable") from error
    headers = limiter.headers_for(decision).as_http_headers()
    response.headers.update(headers)
    if not decision.allowed:
        raise RateLimitExceededError(decision)
    return decision
