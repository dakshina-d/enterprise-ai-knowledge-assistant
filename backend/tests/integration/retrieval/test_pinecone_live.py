"""Explicitly opt-in, non-mutating Pinecone connectivity checks."""

import asyncio
import os

import pytest
from enterprise_ai.retrieval.config import RetrievalSettings
from enterprise_ai.retrieval.pinecone_client import PineconeSdkGateway

pytestmark = pytest.mark.pinecone_live


@pytest.mark.skipif(
    os.getenv("RUN_PINECONE_LIVE_TESTS", "").lower() != "true",
    reason="Pinecone live tests require explicit opt-in",
)
def test_configured_model_and_existing_index_are_accessible() -> None:
    async def check() -> None:
        settings = RetrievalSettings()
        settings.require_enabled()
        gateway = PineconeSdkGateway(settings)
        try:
            model = await gateway.get_model(model=settings.pinecone_dense_model)
            index = await gateway.describe_index(settings.pinecone_index_name)
            assert model is not None
            assert index is not None
        finally:
            await gateway.close()

    asyncio.run(check())
