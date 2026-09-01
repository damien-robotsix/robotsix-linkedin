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


@pytest.mark.asyncio
async def test_chat_skill_returns_200_markdown(client):
    """GET /chat-skill returns the SKILL.md document as text/markdown."""
    resp = await client.get("/chat-skill")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "name: robotsix-linkedin" in resp.text


@pytest.mark.asyncio
async def test_organizations_without_auth_returns_401(client):
    """Calling /organizations without an access token should return 401."""
    resp = await client.get("/organizations")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_organizations_without_org_scope_returns_403(client):
    """Without an org scope on the token, /organizations returns a clear 403."""
    import linkedin_service.auth as auth_mod

    auth_mod.tokens.access_token = "token"
    resp = await client.get("/organizations")
    assert resp.status_code == 403
    assert "Community Management" in resp.text


@pytest.mark.asyncio
async def test_organizations_returns_companies(client, monkeypatch):
    """With an org scope and a successful API call, /organizations lists them."""
    import linkedin_service.auth as auth_mod

    auth_mod.tokens.access_token = "token"
    monkeypatch.setattr(auth_mod.settings, "linkedin_scopes", "r_organization_social")

    async def fake_list_organizations():
        return {"elements": [{"id": "987654", "name": "Robotsix"}]}

    monkeypatch.setattr(auth_mod, "list_organizations", fake_list_organizations)
    resp = await client.get("/organizations")
    assert resp.status_code == 200
    assert resp.json()["elements"][0]["name"] == "Robotsix"


@pytest.mark.asyncio
async def test_organization_detail_without_org_scope_returns_403(client):
    """Without an org scope, /organizations/{id} returns a clear 403."""
    import linkedin_service.auth as auth_mod

    auth_mod.tokens.access_token = "token"
    resp = await client.get("/organizations/987654")
    assert resp.status_code == 403
    assert "Community Management" in resp.text


@pytest.mark.asyncio
async def test_organization_detail_returns_company(client, monkeypatch):
    """With an org scope and a successful API call, /organizations/{id} returns details."""
    import linkedin_service.auth as auth_mod

    auth_mod.tokens.access_token = "token"
    monkeypatch.setattr(auth_mod.settings, "linkedin_scopes", "rw_organization_admin")

    async def fake_get_organization(organization_id):
        return {"id": organization_id, "name": "Robotsix", "vanity_name": "robotsix"}

    monkeypatch.setattr(auth_mod, "get_organization", fake_get_organization)
    resp = await client.get("/organizations/987654")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Robotsix"
