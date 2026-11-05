"""Tests for read and write endpoints."""

from __future__ import annotations

import pytest
from pydantic import SecretStr


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


@pytest.mark.asyncio
async def test_chat_skill_returns_200_markdown(client):
    """GET /chat-skill returns the SKILL.md document as text/markdown."""
    resp = await client.get("/chat-skill")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "name: robotsix-linkedin" in resp.text


def test_chat_skill_route_parity():
    """The chat-skill descriptor documents exactly the app's real routes."""
    from robotsix_http.fastapi import assert_chat_skill_route_parity

    from linkedin_service.app import CHAT_SKILL_PATH, app

    assert_chat_skill_route_parity(app, CHAT_SKILL_PATH.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_org_login_without_org_credentials_returns_503(client):
    """Without the dedicated org app, /auth/org/login returns 503."""
    resp = await client.get("/auth/org/login", follow_redirects=False)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_org_callback_missing_params_returns_422(client):
    """Missing required query params on /auth/org/callback return 422."""
    resp = await client.get("/auth/org/callback")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_organizations_without_auth_returns_401(client):
    """Calling /organizations without an org token should return 401."""
    resp = await client.get("/organizations")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_organizations_without_org_scope_returns_403(client):
    """Without a configured org app, /organizations returns a clear 403."""
    import linkedin_service.auth as auth_mod

    auth_mod.org_tokens.access_token = "org-token"
    resp = await client.get("/organizations")
    assert resp.status_code == 403
    assert "Community Management" in resp.text


@pytest.mark.asyncio
async def test_organizations_returns_companies(client, monkeypatch):
    """With an org app and a successful API call, /organizations lists them."""
    import linkedin_service.auth as auth_mod

    auth_mod.org_tokens.access_token = "org-token"
    monkeypatch.setattr(auth_mod.settings, "linkedin_org_client_id", SecretStr("org-cid"))
    monkeypatch.setattr(auth_mod.settings, "linkedin_org_client_secret", SecretStr("org-secret"))

    async def fake_list_organizations():
        return {"elements": [{"id": "987654", "name": "Robotsix"}]}

    monkeypatch.setattr(auth_mod, "list_organizations", fake_list_organizations)
    resp = await client.get("/organizations")
    assert resp.status_code == 200
    assert resp.json()["elements"][0]["name"] == "Robotsix"


@pytest.mark.asyncio
async def test_organization_detail_without_org_scope_returns_403(client):
    """Without a configured org app, /organizations/{id} returns a clear 403."""
    import linkedin_service.auth as auth_mod

    auth_mod.org_tokens.access_token = "org-token"
    resp = await client.get("/organizations/987654")
    assert resp.status_code == 403
    assert "Community Management" in resp.text


@pytest.mark.asyncio
async def test_organization_detail_returns_company(client, monkeypatch):
    """With an org app and a successful API call, /organizations/{id} returns details."""
    import linkedin_service.auth as auth_mod

    auth_mod.org_tokens.access_token = "org-token"
    monkeypatch.setattr(auth_mod.settings, "linkedin_org_client_id", SecretStr("org-cid"))
    monkeypatch.setattr(auth_mod.settings, "linkedin_org_client_secret", SecretStr("org-secret"))
    monkeypatch.setattr(auth_mod.settings, "linkedin_org_scopes", "r_organization_social")

    async def fake_get_organization(organization_id):
        return {"id": organization_id, "name": "Robotsix", "vanity_name": "robotsix"}

    monkeypatch.setattr(auth_mod, "get_organization", fake_get_organization)
    resp = await client.get("/organizations/987654")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Robotsix"


@pytest.fixture
def share_spy(monkeypatch):
    """Authenticate and replace ``auth.share_content`` with a recorder."""
    import linkedin_service.auth as auth_mod

    auth_mod.tokens.access_token = "token"
    monkeypatch.setattr(auth_mod.settings, "require_operator_confirmation", True)
    calls: list[tuple[str, str]] = []

    async def fake_share_content(text, visibility):
        calls.append((text, visibility))
        return {"id": "urn:li:share:1"}

    monkeypatch.setattr(auth_mod, "share_content", fake_share_content)
    return calls


async def _issue_token(client, text="A", visibility="CONNECTIONS"):
    resp = await client.post("/share", params={"text": text, "visibility": visibility})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmation_required"
    assert body["confirmation_token"]
    return body["confirmation_token"]


@pytest.mark.asyncio
async def test_share_first_call_requires_confirmation(client, share_spy):
    """The first /share call issues a token and does not post."""
    await _issue_token(client)
    assert share_spy == []


@pytest.mark.asyncio
async def test_share_resubmit_with_matching_token_posts(client, share_spy):
    """Resubmitting the same text/visibility with the token posts."""
    token = await _issue_token(client)
    resp = await client.post(
        "/share",
        params={"text": "A", "visibility": "CONNECTIONS", "confirmation_token": token},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "posted"
    assert share_spy == [("A", "CONNECTIONS")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"text": "B", "visibility": "CONNECTIONS"},
        {"text": "A", "visibility": "PUBLIC"},
    ],
)
async def test_share_resubmit_with_different_payload_rejected(client, share_spy, params):
    """A token approved for one payload cannot post different text/visibility."""
    token = await _issue_token(client)
    resp = await client.post("/share", params={**params, "confirmation_token": token})
    assert resp.status_code == 400
    assert share_spy == []


@pytest.mark.asyncio
async def test_share_token_is_single_use(client, share_spy):
    """A confirmation token cannot be replayed."""
    token = await _issue_token(client)
    params = {"text": "A", "visibility": "CONNECTIONS", "confirmation_token": token}
    assert (await client.post("/share", params=params)).status_code == 200
    resp = await client.post("/share", params=params)
    assert resp.status_code == 400
    assert share_spy == [("A", "CONNECTIONS")]


@pytest.mark.asyncio
async def test_share_expired_token_rejected(client, share_spy):
    """A token older than the TTL is rejected and purged."""
    from linkedin_service.auth import _pending_confirmations
    from linkedin_service.auth.tokens import CONFIRMATION_TOKEN_TTL_SECONDS

    token = await _issue_token(client)
    _pending_confirmations[token]["issued_at"] -= CONFIRMATION_TOKEN_TTL_SECONDS + 1
    resp = await client.post(
        "/share",
        params={"text": "A", "visibility": "CONNECTIONS", "confirmation_token": token},
    )
    assert resp.status_code == 400
    assert token not in _pending_confirmations
    assert share_spy == []


@pytest.mark.asyncio
async def test_share_expired_tokens_purged_on_generate(client, share_spy):
    """Issuing a new token purges expired pending confirmations."""
    from linkedin_service.auth import _pending_confirmations
    from linkedin_service.auth.tokens import CONFIRMATION_TOKEN_TTL_SECONDS

    old = await _issue_token(client)
    _pending_confirmations[old]["issued_at"] -= CONFIRMATION_TOKEN_TTL_SECONDS + 1
    new = await _issue_token(client)
    assert old not in _pending_confirmations
    assert new in _pending_confirmations


@pytest.mark.asyncio
async def test_share_without_confirmation_setting_posts_directly(client, share_spy, monkeypatch):
    """With require_operator_confirmation=False the post goes straight through."""
    import linkedin_service.auth as auth_mod

    monkeypatch.setattr(auth_mod.settings, "require_operator_confirmation", False)
    resp = await client.post("/share", params={"text": "A"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "posted"
    assert share_spy == [("A", "PUBLIC")]
