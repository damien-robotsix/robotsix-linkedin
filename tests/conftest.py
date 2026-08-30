"""Shared test fixtures."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from linkedin_service import auth
from linkedin_service.app import app


@pytest.fixture(autouse=True)
def reset_token_state():
    """Reset the module-level token store between tests for isolation."""
    auth.tokens.access_token = ""
    auth.tokens.refresh_token = ""
    auth.tokens.expires_at = 0.0
    auth.tokens.state = ""
    auth._pending_confirmations.clear()
    yield


@pytest.fixture
async def client():
    """Async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
