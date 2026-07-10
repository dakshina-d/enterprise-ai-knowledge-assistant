"""Process health endpoints."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Stable health-check response contract."""

    status: Literal["healthy"]


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    """Report that the API process is running."""
    return HealthResponse(status="healthy")


@router.get("/ready", response_model=HealthResponse)
async def ready() -> HealthResponse:
    """Report placeholder readiness before dependencies are introduced."""
    return HealthResponse(status="healthy")
