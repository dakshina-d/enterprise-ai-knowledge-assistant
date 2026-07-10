"""Proof-of-concept authentication endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from enterprise_ai.api.dependencies import (
    get_authentication_service,
    get_authorization_service,
    get_token_service,
)
from enterprise_ai.models.identity import (
    LoginRequest,
    LoginResponse,
    PublicPrincipalProfile,
)
from enterprise_ai.rate_limit.dependencies import (
    RateLimitedPrincipal,
    enforce_login_rate_limit,
)
from enterprise_ai.rate_limit.models import RateLimitDecision
from enterprise_ai.security.authentication import AuthenticationService
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.security.exceptions import AuthenticationError
from enterprise_ai.security.token import TokenService

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
logger = logging.getLogger(__name__)


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    _rate_limit: Annotated[RateLimitDecision, Depends(enforce_login_rate_limit)],
    authentication: Annotated[AuthenticationService, Depends(get_authentication_service)],
    authorization: Annotated[AuthorizationService, Depends(get_authorization_service)],
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> LoginResponse:
    try:
        profile = authentication.authenticate(request.username, request.password)
    except AuthenticationError:
        logger.warning("authentication_failed", extra={"outcome": "denied"})
        raise
    permissions = authorization.permissions_for_role(profile.role)
    access_token = tokens.issue_token(profile, permissions)
    principal = tokens.decode_principal(access_token)
    logger.info(
        "authentication_succeeded",
        extra={
            "user_id": str(profile.user_id),
            "role": profile.role.value,
            "outcome": "allowed",
        },
    )
    return LoginResponse(
        access_token=access_token,
        expires_in=tokens.expires_in_seconds,
        user=profile,
        permissions=permissions,
        expires_at=principal.expires_at,
    )


@router.get("/me", response_model=PublicPrincipalProfile)
async def current_user(principal: RateLimitedPrincipal) -> PublicPrincipalProfile:
    logger.info(
        "protected_endpoint_accessed",
        extra={
            "user_id": str(principal.identity.user_id),
            "role": principal.identity.role.value,
            "outcome": "allowed",
        },
    )
    return PublicPrincipalProfile(
        user_id=principal.identity.user_id,
        username=principal.identity.username,
        display_name=principal.identity.display_name,
        role=principal.identity.role,
        permissions=principal.permissions,
    )
