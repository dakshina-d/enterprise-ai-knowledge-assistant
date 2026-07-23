"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware

from enterprise_ai.api.auth import router as auth_router
from enterprise_ai.api.chat import router as chat_router
from enterprise_ai.api.errors import (
    ChatAPIError,
    chat_error_handler,
    http_error_handler,
    validation_error_handler,
)
from enterprise_ai.api.health import router as health_router
from enterprise_ai.api.rate_limit_errors import (
    rate_limit_exceeded_handler,
    rate_limit_unavailable_handler,
)
from enterprise_ai.api.runtime import create_api_runtime
from enterprise_ai.api.security_errors import security_error_handler
from enterprise_ai.core.config import Settings, get_settings
from enterprise_ai.core.logging import configure_logging
from enterprise_ai.graph.runtime import GraphRuntime
from enterprise_ai.rate_limit.clock import MonotonicClock
from enterprise_ai.rate_limit.dependencies import (
    RateLimitExceededError,
    RateLimitUnavailableError,
)
from enterprise_ai.rate_limit.policy import policies_from_settings
from enterprise_ai.rate_limit.store import InMemoryBucketStore
from enterprise_ai.rate_limit.token_bucket import TokenBucketRateLimiter
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.security.authentication import (
    AuthenticationService,
    configured_users_from_settings,
)
from enterprise_ai.security.authorization import AuthorizationService
from enterprise_ai.security.exceptions import SecurityError
from enterprise_ai.security.password import PasswordService
from enterprise_ai.security.token import TokenService

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    runtime_factory: Callable[[RetrievalSettings], GraphRuntime] | None = None,
) -> FastAPI:
    """Create and configure an isolated FastAPI application instance."""
    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)
    make_runtime = runtime_factory or create_api_runtime

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        runtime: GraphRuntime | None = None
        if active_settings.auth_enabled:
            runtime = make_runtime(RetrievalSettings())
            application.state.graph_runtime = runtime
        try:
            yield
        finally:
            if runtime is not None:
                await runtime.aclose()

    application = FastAPI(
        title="Enterprise AI Knowledge Assistant",
        version="0.1.0",
        description="Authenticated asynchronous graph chat API with native SSE streaming.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(active_settings.api_allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=[
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "Retry-After",
        ],
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = monotonic()
        request.state.request_id = uuid4()
        request.state.trace_id = uuid4()
        response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if response.headers.get("Content-Type", "").startswith("text/event-stream"):
            response.headers["Cache-Control"] = "no-cache, no-transform"
            response.headers["X-Accel-Buffering"] = "no"
        logger.info(
            "http_request_completed",
            extra={
                "request_id": str(request.state.request_id),
                "trace_id": str(request.state.trace_id),
                "endpoint": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "duration_category": ("fast" if monotonic() - started < 1 else "bounded"),
            },
        )
        return response

    application.include_router(health_router)
    application.exception_handler(SecurityError)(security_error_handler)
    application.exception_handler(RateLimitExceededError)(rate_limit_exceeded_handler)
    application.exception_handler(RateLimitUnavailableError)(rate_limit_unavailable_handler)
    application.exception_handler(ChatAPIError)(chat_error_handler)
    application.exception_handler(RequestValidationError)(validation_error_handler)
    application.exception_handler(HTTPException)(http_error_handler)
    application.state.settings = active_settings
    application.state.rate_limiter = TokenBucketRateLimiter(
        enabled=active_settings.rate_limit_enabled,
        policies=policies_from_settings(active_settings),
        store=InMemoryBucketStore(ttl_seconds=active_settings.rate_limit_bucket_ttl_seconds),
        clock=MonotonicClock(),
    )
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
        application.include_router(auth_router)
    application.include_router(chat_router)
    return application


def app() -> FastAPI:
    """Expose an application factory for Uvicorn's ``--factory`` mode."""
    return create_app()
