"""Shared test fixtures."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from linkedin_service import auth
from linkedin_service.app import app


@pytest.fixture(autouse=True)
def reset_token_state(tmp_path):
    """Reset the module-level token stores between tests for isolation."""
    # Point persistence at an isolated temp file so tests never read or
    # write the operator's real token file.
    auth.settings.linkedin_token_file = str(tmp_path / "tokens.json")
    auth.settings.linkedin_org_token_file = str(tmp_path / "org-tokens.json")
    # Reset BOTH token stores (personal + dedicated org app) for isolation.
    for store in (auth.tokens, auth.org_tokens):
        store.access_token = ""
        store.refresh_token = ""
        store.expires_at = 0.0
        store.state = ""
    # Org app credentials default to unconfigured so organization tests
    # exercise the clear 403 path unless they explicitly opt in.
    auth.settings.linkedin_org_client_id = SecretStr("")
    auth.settings.linkedin_org_client_secret = SecretStr("")
    auth._pending_confirmations.clear()
    yield


@pytest.fixture
async def client():
    """Async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
