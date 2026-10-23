"""Personal-account LinkedIn app: OAuth flow and member API wrappers."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from .tokens import (
    API_BASE,
    OAuthApp,
    _app_auth_headers,
    _build_app_authorize_url,
    _exchange_app_code,
    _refresh_app_access_token,
    _retry_send,
    _validate_app_redirect_uri,
    tokens,
)

PERSONAL_APP = OAuthApp(
    tokens=tokens,
    configured=lambda: settings.auth_configured,
    client_id=lambda: settings.linkedin_client_id.get_secret_value(),
    client_secret=lambda: settings.linkedin_client_secret.get_secret_value(),
    redirect_uri=lambda: settings.linkedin_redirect_uri,
    allowed_redirect_uris=lambda: settings.allowed_redirect_uris_list,
    scopes=lambda: settings.linkedin_scopes_list,
    token_file=lambda: settings.linkedin_token_file,
    not_configured_message="LinkedIn client credentials are not configured.",
    allowlist_label="allowlist",
    refresh_label="refresh token",
)


def validate_redirect_uri(uri: str) -> None:
    """Ensure ``uri`` is on the configured allowlist.

    Raises :class:`ValueError` when the redirect URI is not permitted,
    guarding against open-redirect / token-exfiltration attacks.
    """
    _validate_app_redirect_uri(PERSONAL_APP, uri)


def build_authorize_url() -> str:
    """Return the LinkedIn consent-screen URL.

    Raises RuntimeError if credentials are not configured and ValueError if
    the configured redirect URI is not on the allowlist.
    """
    return _build_app_authorize_url(PERSONAL_APP)


async def exchange_code(code: str, state: str) -> dict[str, Any]:
    """Exchange an authorization code for access + refresh tokens.

    Returns the token response dict.  Raises on mismatched state or
    HTTP error.
    """
    return await _exchange_app_code(PERSONAL_APP, code, state)


async def refresh_access_token() -> dict[str, Any]:
    """Use the stored refresh token to obtain a new access token.

    Refresh is deliberately manual: it is not wired into the request path,
    so callers must invoke it explicitly when ``tokens.expires_at`` passes.
    """
    return await _refresh_app_access_token(PERSONAL_APP)


# ---------------------------------------------------------------------------
# LinkedIn API wrappers
# ---------------------------------------------------------------------------


def _auth_headers() -> dict[str, str]:
    return _app_auth_headers(PERSONAL_APP)


async def get_profile() -> dict[str, Any]:
    """Fetch the authenticated member's profile (OpenID Connect userinfo)."""
    async with httpx.AsyncClient() as client:
        resp = await _retry_send(client, "GET", f"{API_BASE}/userinfo", headers=_auth_headers())
    result: dict[str, Any] = resp.json()
    return result


async def share_content(text: str, visibility: str = "PUBLIC") -> dict[str, Any]:
    """Post a share / UGC on behalf of the authenticated member.

    This is a **state-mutating** action — callers MUST gate it behind
    operator confirmation.
    """
    # First fetch the member's person URN
    profile = await get_profile()
    person_urn = f"urn:li:person:{profile['sub']}"
    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
    }
    async with httpx.AsyncClient() as client:
        resp = await _retry_send(
            client,
            "POST",
            f"{API_BASE}/ugcPosts",
            json=payload,
            headers=_auth_headers(),
        )
    # LinkedIn returns the created post URN in the X-RestLi-Id header; the
    # body may also carry an "id". Prefer the header, fall back to the body.
    body: dict[str, Any] = {}
    if resp.content:
        try:
            body = resp.json()
        except ValueError:
            body = {}
    urn = resp.headers.get("x-restli-id") or body.get("id")
    return {"id": urn, "urn": urn, "author": person_urn, "response": body}
