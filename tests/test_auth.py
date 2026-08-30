"""Tests for OAuth endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_auth_login_without_credentials_returns_503(client):
    """When no LinkedIn credentials are configured, /auth/login returns 503."""
    resp = await client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_auth_callback_missing_params_returns_422(client):
    """Missing required query params should return a validation error."""
    resp = await client.get("/auth/callback")
    assert resp.status_code == 422
