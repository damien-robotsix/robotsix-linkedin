"""Tests for the LinkedIn OAuth token exchange and post-create paths.

Live LinkedIn calls are not possible in CI, so httpx is mocked.
"""

from __future__ import annotations

import os
import stat
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from linkedin_service import auth
from linkedin_service.config import settings


class _FakeResponse:
    """Minimal stand-in for :class:`httpx.Response`."""

    def __init__(
        self,
        *,
        json_data: dict[str, Any] | None = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self._json = json_data if json_data is not None else {}
        self.status_code = status_code
        self.headers = httpx.Headers(headers or {})
        self.text = text
        self.content = b"x" if json_data is not None else b""

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self) -> dict[str, Any]:
        return self._json


class _FakeClient:
    """Async context-manager stand-in for httpx.AsyncClient."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("post", args, kwargs))
        return self._response

    async def get(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        self.calls.append(("get", args, kwargs))
        return self._response


def _patch_client(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> _FakeClient:
    client = _FakeClient(response)
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *a, **k: client)
    return client


@pytest.fixture
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "linkedin_client_id", SecretStr("cid"))
    monkeypatch.setattr(settings, "linkedin_client_secret", SecretStr("csecret"))


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_stores_tokens(
    monkeypatch: pytest.MonkeyPatch, _credentials: None
) -> None:
    response = _FakeResponse(
        json_data={
            "access_token": "abc123",
            "refresh_token": "refresh123",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
    )
    _patch_client(monkeypatch, response)
    auth.tokens.state = "state-1"

    data = await auth.exchange_code("the-code", "state-1")

    assert data["access_token"] == "abc123"
    assert auth.tokens.access_token == "abc123"
    assert auth.tokens.refresh_token == "refresh123"
    # expires_at must be an absolute future timestamp, not the raw duration.
    assert auth.tokens.expires_at > 3600


@pytest.mark.asyncio
async def test_exchange_code_state_mismatch_raises() -> None:
    auth.tokens.state = "expected"
    with pytest.raises(ValueError, match="state mismatch"):
        await auth.exchange_code("code", "tampered")


@pytest.mark.asyncio
async def test_exchange_code_surfaces_api_error(
    monkeypatch: pytest.MonkeyPatch, _credentials: None
) -> None:
    response = _FakeResponse(
        json_data=None,
        status_code=400,
        text='{"error":"invalid_grant"}',
    )
    _patch_client(monkeypatch, response)
    auth.tokens.state = "s"

    with pytest.raises(auth.LinkedInAPIError) as exc:
        await auth.exchange_code("bad", "s")
    assert exc.value.status_code == 400
    assert "invalid_grant" in str(exc.value)


# ---------------------------------------------------------------------------
# Authorize URL / redirect allowlist
# ---------------------------------------------------------------------------


def test_build_authorize_url_contains_scopes_and_state(
    monkeypatch: pytest.MonkeyPatch, _credentials: None
) -> None:
    url = auth.build_authorize_url()
    assert url.startswith(auth.AUTHORIZE_URL)
    assert "w_member_social" in url
    assert auth.tokens.state and auth.tokens.state in url


def test_validate_redirect_uri_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        auth.validate_redirect_uri("https://evil.example.com/callback")


def test_validate_redirect_uri_accepts_configured() -> None:
    # The configured redirect URI is always on the allowlist.
    auth.validate_redirect_uri(settings.linkedin_redirect_uri)


# ---------------------------------------------------------------------------
# Post create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_share_content_returns_urn(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_profile() -> dict[str, Any]:
        return {"sub": "member-42"}

    monkeypatch.setattr(auth, "get_profile", fake_profile)
    response = _FakeResponse(
        status_code=201,
        headers={"x-restli-id": "urn:li:share:99999"},
    )
    _patch_client(monkeypatch, response)
    auth.tokens.access_token = "token"

    result = await auth.share_content("hello world", "PUBLIC")

    assert result["id"] == "urn:li:share:99999"
    assert result["urn"] == "urn:li:share:99999"
    assert result["author"] == "urn:li:person:member-42"


@pytest.mark.asyncio
async def test_share_content_surfaces_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_profile() -> dict[str, Any]:
        return {"sub": "member-42"}

    monkeypatch.setattr(auth, "get_profile", fake_profile)
    response = _FakeResponse(
        json_data=None,
        status_code=403,
        text='{"message":"Not enough permissions"}',
    )
    _patch_client(monkeypatch, response)
    auth.tokens.access_token = "token"

    with pytest.raises(auth.LinkedInAPIError) as exc:
        await auth.share_content("hello", "PUBLIC")
    assert exc.value.status_code == 403
    assert "permissions" in str(exc.value)


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_persists_tokens_to_file(
    monkeypatch: pytest.MonkeyPatch, _credentials: None
) -> None:
    response = _FakeResponse(
        json_data={
            "access_token": "abc123",
            "refresh_token": "refresh123",
            "expires_in": 3600,
        }
    )
    _patch_client(monkeypatch, response)
    auth.tokens.state = "s"

    await auth.exchange_code("code", "s")

    token_path = settings.linkedin_token_file
    assert os.path.exists(token_path)
    # File must be 0600 inside a 0700 directory.
    assert stat.S_IMODE(os.stat(token_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(token_path)).st_mode) == 0o700

    # A fresh TokenStore loading the same file recovers the tokens,
    # proving they survive a restart.
    fresh = auth.TokenStore()
    fresh.load()
    assert fresh.access_token == "abc123"
    assert fresh.refresh_token == "refresh123"
    # The CSRF state nonce is not persisted.
    assert fresh.state == ""


def test_token_store_save_load_roundtrip() -> None:
    store = auth.TokenStore(access_token="a", refresh_token="r", expires_at=123.0, state="nonce")
    store.save()

    loaded = auth.TokenStore()
    loaded.load()
    assert loaded.access_token == "a"
    assert loaded.refresh_token == "r"
    assert loaded.expires_at == 123.0
