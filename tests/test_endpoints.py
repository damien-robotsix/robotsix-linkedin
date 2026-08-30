"""Tests for read and write endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_me_without_auth_returns_401(client):
    """Calling /me without an access token should return 401."""
    resp = await client.get("/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_share_without_auth_returns_401(client):
    """Calling /share without an access token should return 401."""
    resp = await client.post("/share", params={"text": "hello"})
    assert resp.status_code == 401
