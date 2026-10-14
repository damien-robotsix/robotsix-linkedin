"""Tests for OAuth endpoints."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from linkedin_service.auth import TokenStore


def test_token_store_round_trip(tmp_path):
    """Saved tokens are recovered verbatim by a fresh store load."""
    path = str(tmp_path / "tokens.json")
    writer = TokenStore(
        access_token="acc-123",
        refresh_token="ref-456",
        expires_at=1700.5,
        state="nonce-should-not-persist",
    )
    writer.save(path)

    reader = TokenStore()
    reader.load(path)

    assert reader.access_token == "acc-123"
    assert reader.refresh_token == "ref-456"
    assert reader.expires_at == 1700.5


def test_token_store_excludes_state_from_disk(tmp_path):
    """The transient CSRF ``state`` nonce is never written to disk."""
    path = Path(tmp_path / "tokens.json")
    TokenStore(
        access_token="acc-123",
        refresh_token="ref-456",
        expires_at=1700.5,
        state="nonce-should-not-persist",
    ).save(str(path))

    persisted = json.loads(path.read_text())
    assert "state" not in persisted
    assert persisted == {
        "access_token": "acc-123",
        "refresh_token": "ref-456",
        "expires_at": 1700.5,
    }

    # A fresh store starts with an empty state, confirming state is not
    # recovered on load.
    reader = TokenStore()
    reader.load(str(path))
    assert reader.state == ""


def test_token_store_uses_secure_file_and_dir_permissions(tmp_path):
    """Persisted token file is 0600 inside a 0700 directory."""
    token_dir = tmp_path / "secrets"
    path = token_dir / "tokens.json"
    TokenStore(access_token="acc-123").save(str(path))

    file_mode = stat.S_IMODE(path.stat().st_mode)
    dir_mode = stat.S_IMODE(token_dir.stat().st_mode)
    assert file_mode == 0o600
    assert dir_mode == 0o700


def test_token_store_empty_path_disables_persistence(tmp_path, monkeypatch):
    """An empty configured path makes save/load a silent no-op."""
    monkeypatch.chdir(tmp_path)

    store = TokenStore(access_token="acc-123", refresh_token="ref-456")
    store.save("")  # must not raise and must not create any file

    assert list(tmp_path.iterdir()) == []

    reader = TokenStore(access_token="preexisting")
    reader.load("")  # no file configured -> leave in-memory fields untouched
    assert reader.access_token == "preexisting"


def test_token_store_missing_file_is_cold_start(tmp_path):
    """Loading from an absent file degrades to a cold start, not an error."""
    reader = TokenStore(access_token="preexisting")
    reader.load(str(tmp_path / "does-not-exist.json"))
    assert reader.access_token == "preexisting"


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
