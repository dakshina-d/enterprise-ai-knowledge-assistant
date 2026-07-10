"""FastAPI application entry point."""

from fastapi import FastAPI

from enterprise_ai.api.health import router as health_router
from enterprise_ai.core.config import get_settings
from enterprise_ai.core.logging import configure_logging


def create_app() -> FastAPI:
    """Create and configure an isolated FastAPI application instance."""
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="Enterprise AI Knowledge Assistant",
        version="0.1.0",
        description="Health-check baseline; AI capabilities are not implemented.",
    )
    application.include_router(health_router)
    return application


def app() -> FastAPI:
    """Expose an application factory for Uvicorn's ``--factory`` mode."""
    return create_app()
