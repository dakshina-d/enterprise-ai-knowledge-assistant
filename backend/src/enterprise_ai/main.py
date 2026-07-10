"""FastAPI application entry point."""

from fastapi import FastAPI

from enterprise_ai.api.auth import router as auth_router
from enterprise_ai.api.health import router as health_router
from enterprise_ai.api.rate_limit_errors import (
    rate_limit_exceeded_handler,
    rate_limit_unavailable_handler,
)
from enterprise_ai.api.security_errors import security_error_handler
from enterprise_ai.core.config import Settings, get_settings
from enterprise_ai.core.logging import configure_logging
from enterprise_ai.rate_limit.clock import MonotonicClock
from enterprise_ai.rate_limit.dependencies import (
    RateLimitExceededError,
    RateLimitUnavailableError,
)
from enterprise_ai.rate_limit.policy import policies_from_settings
from enterprise_ai.rate_limit.store import InMemoryBucketStore
from enterprise_ai.rate_limit.token_bucket import TokenBucketRateLimiter
from enterprise_ai.security.authentication import (
    AuthenticationService,
    configured_users_from_settings,
)
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.security.exceptions import SecurityError
from enterprise_ai.security.password import PasswordService
from enterprise_ai.security.token import TokenService


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure an isolated FastAPI application instance."""
    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)

    application = FastAPI(
        title="Enterprise AI Knowledge Assistant",
        version="0.1.0",
        description="Health and proof-of-concept authentication baseline.",
    )
    application.include_router(health_router)
    application.exception_handler(SecurityError)(security_error_handler)
    application.exception_handler(RateLimitExceededError)(rate_limit_exceeded_handler)
    application.exception_handler(RateLimitUnavailableError)(rate_limit_unavailable_handler)
    application.state.settings = active_settings
    if active_settings.auth_enabled:
        secret = active_settings.auth_token_secret
        if secret is None:
            raise ValueError("authentication signing secret is required")
        password_service = PasswordService()
        application.state.authentication_service = AuthenticationService(
            configured_users_from_settings(active_settings), password_service
        )
        application.state.authorization_service = AuthorizationService()
        application.state.token_service = TokenService(
            secret=secret.get_secret_value(),
            algorithm=active_settings.auth_token_algorithm,
            issuer=active_settings.auth_token_issuer,
            audience=active_settings.auth_token_audience,
            expiry_minutes=active_settings.auth_token_expiry_minutes,
        )
        application.state.rate_limiter = TokenBucketRateLimiter(
            enabled=active_settings.rate_limit_enabled,
            policies=policies_from_settings(active_settings),
            store=InMemoryBucketStore(ttl_seconds=active_settings.rate_limit_bucket_ttl_seconds),
            clock=MonotonicClock(),
        )
        application.include_router(auth_router)
    return application


def app() -> FastAPI:
    """Expose an application factory for Uvicorn's ``--factory`` mode."""
    return create_app()
