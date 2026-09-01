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
# Org-app OAuth flow
# ---------------------------------------------------------------------------


@pytest.fixture
def _org_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure the dedicated org LinkedIn app."""
    monkeypatch.setattr(settings, "linkedin_org_client_id", SecretStr("org-cid"))
    monkeypatch.setattr(settings, "linkedin_org_client_secret", SecretStr("org-secret"))


def test_build_org_authorize_url_uses_org_credentials(
    monkeypatch: pytest.MonkeyPatch, _org_credentials: None
) -> None:
    url = auth.build_org_authorize_url()
    assert url.startswith(auth.AUTHORIZE_URL)
    assert "client_id=org-cid" in url
    assert "r_organization_social" in url
    assert auth.org_tokens.state and auth.org_tokens.state in url


def test_build_org_authorize_url_raises_without_org_credentials() -> None:
    with pytest.raises(RuntimeError, match="org app credentials"):
        auth.build_org_authorize_url()


@pytest.mark.asyncio
async def test_exchange_org_code_stores_in_org_token_store(
    monkeypatch: pytest.MonkeyPatch, _org_credentials: None
) -> None:
    response = _FakeResponse(
        json_data={
            "access_token": "org-abc123",
            "refresh_token": "org-refresh123",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
    )
    client = _patch_client(monkeypatch, response)
    auth.org_tokens.state = "org-state-1"
    # The personal token must stay untouched by the org flow.
    auth.tokens.access_token = "personal-token"

    data = await auth.exchange_org_code("the-code", "org-state-1")

    assert data["access_token"] == "org-abc123"
    assert auth.org_tokens.access_token == "org-abc123"
    assert auth.org_tokens.refresh_token == "org-refresh123"
    assert auth.org_tokens.expires_at > 3600
    # Personal store is not clobbered.
    assert auth.tokens.access_token == "personal-token"
    _, args, kwargs = client.calls[0]
    assert args[0] == auth.ACCESS_TOKEN_URL
    assert kwargs["data"]["client_id"] == "org-cid"
    assert kwargs["data"]["client_secret"] == "org-secret"
    assert kwargs["data"]["redirect_uri"] == settings.linkedin_org_redirect_uri


@pytest.mark.asyncio
async def test_exchange_org_code_state_mismatch_raises() -> None:
    auth.org_tokens.state = "expected"
    with pytest.raises(ValueError, match="state mismatch"):
        await auth.exchange_org_code("code", "tampered")


# ---------------------------------------------------------------------------
# Organization reads
# ---------------------------------------------------------------------------


def test_require_org_scope_raises_when_org_app_missing() -> None:
    with pytest.raises(auth.OrgAppNotConfiguredError):
        auth._require_org_scope()


def test_require_org_scope_raises_without_org_scope(
    monkeypatch: pytest.MonkeyPatch, _org_credentials: None
) -> None:
    monkeypatch.setattr(settings, "linkedin_org_scopes", "openid profile email")
    with pytest.raises(auth.LinkedInScopeMissingError):
        auth._require_org_scope()


def test_require_org_scope_passes_with_org_scope(
    monkeypatch: pytest.MonkeyPatch, _org_credentials: None
) -> None:
    # Default linkedin_org_scopes already includes org read scopes.
    auth._require_org_scope()  # must not raise


@pytest.mark.asyncio
async def test_list_organizations_returns_companies(
    monkeypatch: pytest.MonkeyPatch, _org_credentials: None
) -> None:
    response = _FakeResponse(
        json_data={
            "elements": [
                {
                    "organization": {
                        "id": "987654",
                        "localizedName": "Robotsix",
                        "vanityName": "robotsix",
                        "logoV2": {
                            # Real API: original is the image URN string and
                            # the resolved object lives under original~.
                            "original": "urn:li:digitalmediaAsset:C5600AQAbc",
                            "original~": {"url": "https://cdn.example/logo.png"},
                        },
                    }
                }
            ]
        }
    )
    client = _patch_client(monkeypatch, response)
    auth.org_tokens.access_token = "org-token"

    result = await auth.list_organizations()

    element = result["elements"][0]
    assert element["id"] == "987654"
    assert element["name"] == "Robotsix"
    assert element["vanity_name"] == "robotsix"
    assert element["logo"] == "https://cdn.example/logo.png"
    _, args, kwargs = client.calls[0]
    assert "organizationAcls" in str(args[0])
    assert kwargs["params"]["q"] == "roleAssignee"
    # Org reads authenticate with the ORG token, not the personal one.
    assert kwargs["headers"]["Authorization"] == "Bearer org-token"


@pytest.mark.asyncio
async def test_list_organizations_raises_when_scope_missing(
    monkeypatch: pytest.MonkeyPatch, _org_credentials: None
) -> None:
    monkeypatch.setattr(settings, "linkedin_org_scopes", "openid profile email")
    auth.org_tokens.access_token = "org-token"
    with pytest.raises(auth.LinkedInScopeMissingError):
        await auth.list_organizations()


@pytest.mark.asyncio
async def test_list_organizations_raises_when_org_app_missing() -> None:
    auth.org_tokens.access_token = "org-token"
    with pytest.raises(auth.OrgAppNotConfiguredError):
        await auth.list_organizations()


@pytest.mark.asyncio
async def test_get_organization_returns_company(
    monkeypatch: pytest.MonkeyPatch, _org_credentials: None
) -> None:
    response = _FakeResponse(
        json_data={
            "id": "987654",
            "localizedName": "Robotsix",
            "vanityName": "robotsix",
            "logoV2": {
                "original": "urn:li:digitalmediaAsset:C5600AQAbc",
                "original~": {
                    "elements": [{"url": "https://cdn.example/logo.png"}]
                },
            },
        }
    )
    client = _patch_client(monkeypatch, response)
    auth.org_tokens.access_token = "org-token"

    result = await auth.get_organization("987654")

    assert result["id"] == "987654"
    assert result["name"] == "Robotsix"
    assert result["vanity_name"] == "robotsix"
    assert result["logo"] == "https://cdn.example/logo.png"
    _, args, kwargs = client.calls[0]
    assert "organizations/987654" in str(args[0])
    assert kwargs["headers"]["Authorization"] == "Bearer org-token"


@pytest.mark.asyncio
async def test_get_organization_surfaces_linkedin_403(
    monkeypatch: pytest.MonkeyPatch, _org_credentials: None
) -> None:
    response = _FakeResponse(
        json_data=None,
        status_code=403,
        text='{"message":"Not enough permissions"}',
    )
    _patch_client(monkeypatch, response)
    auth.org_tokens.access_token = "org-token"

    with pytest.raises(auth.LinkedInAPIError) as exc:
        await auth.get_organization("987654")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_logo_url_never_crashes_on_raw_urn() -> None:
    """A production logoV2 with a string original must not raise."""
    org = {"logoV2": {"original": "urn:li:digitalmediaAsset:C5600AQAbc"}}
    assert auth._logo_url(org) is None


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
