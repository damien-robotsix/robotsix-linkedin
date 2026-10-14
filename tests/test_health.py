"""Tests for the /health endpoint."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_returns_200(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "auth_configured" in body


@pytest.mark.asyncio
async def test_error_responses_use_shared_envelope(client):
    """Errors are rendered into the shared ``{"error": {"code", "detail"}}`` envelope."""
    # ``/me`` requires authentication; with no token the route raises an
    # HTTPException(401) that the shared handler wraps in the envelope.
    resp = await client.get("/me")
    assert resp.status_code == 401
    body = resp.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "detail"}
    assert body["error"]["code"] == "http_error"
    assert body["error"]["detail"] == "Not authenticated. Call /auth/login first."
