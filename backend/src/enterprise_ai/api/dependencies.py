"""Reusable FastAPI authentication and authorization dependencies."""

from collections.abc import Awaitable, Callable
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from enterprise_ai.models.identity import (
    AuthenticatedPrincipal,
    ToolPermission,
    UserRole,
)
from enterprise_ai.security.authentication import AuthenticationService
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.security.exceptions import AuthenticationRequiredError, AuthorizationError
from enterprise_ai.security.token import TokenService

bearer_scheme = HTTPBearer(auto_error=False)


def get_authentication_service(request: Request) -> AuthenticationService:
    return cast(AuthenticationService, request.app.state.authentication_service)


def get_token_service(request: Request) -> TokenService:
    if not hasattr(request.app.state, "token_service"):
        raise AuthenticationRequiredError()
    return cast(TokenService, request.app.state.token_service)


def get_authorization_service(request: Request) -> AuthorizationService:
    return cast(AuthorizationService, request.app.state.authorization_service)


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    token_service: Annotated[TokenService, Depends(get_token_service)],
) -> AuthenticatedPrincipal:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise AuthenticationRequiredError()
    return token_service.decode_principal(credentials.credentials)


CurrentPrincipal = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]


def require_permission(
    permission: ToolPermission,
) -> Callable[..., Awaitable[AuthenticatedPrincipal]]:
    async def dependency(
        principal: CurrentPrincipal,
        authorization: Annotated[AuthorizationService, Depends(get_authorization_service)],
    ) -> AuthenticatedPrincipal:
        authorization.require_permission(principal, permission)
        return principal

    return dependency


def require_role(*roles: UserRole) -> Callable[..., Awaitable[AuthenticatedPrincipal]]:
    allowed = frozenset(roles)

    async def dependency(principal: CurrentPrincipal) -> AuthenticatedPrincipal:
        if principal.identity.role not in allowed:
            raise AuthorizationError(reason_code="authorization.missing_role")
        return principal

    return dependency
