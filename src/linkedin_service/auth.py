"""LinkedIn OAuth 2.0 helper — authorization-code grant flow.

When real credentials are not configured the module exposes stub
endpoints so the service still boots and /health passes.
"""

from __future__ import annotations

import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings

# LinkedIn OAuth 2.0 endpoints (v2)
AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
ACCESS_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API_BASE = "https://api.linkedin.com/v2"


class LinkedInAPIError(RuntimeError):
    """Raised when LinkedIn returns a non-2xx response.

    Carries the HTTP status and response body so callers can surface the
    underlying LinkedIn error to operators instead of an opaque failure.
    """

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"LinkedIn API returned {status_code}: {body}")


def _raise_for_status(resp: httpx.Response) -> None:
    """Raise :class:`LinkedInAPIError` with the response body on error."""
    if resp.is_error:
        raise LinkedInAPIError(resp.status_code, resp.text)


@dataclass
class TokenStore:
    """In-memory token storage (swap for EnvStore / vault in production)."""

    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0  # unix timestamp
    state: str = ""


tokens = TokenStore()

# Pending confirmation tokens for write operations.
_pending_confirmations: dict[str, dict[str, Any]] = {}


def generate_confirmation_token(payload: dict[str, Any]) -> str:
    """Issue a one-time confirmation token for a state-mutating action."""
    token = secrets.token_urlsafe(32)
    _pending_confirmations[token] = payload
    return token


def consume_confirmation_token(token: str) -> dict[str, Any] | None:
    """Consume (pop) a confirmation token. Returns the payload or None."""
    return _pending_confirmations.pop(token, None)


# ---------------------------------------------------------------------------
# Auth flow helpers
# ---------------------------------------------------------------------------

def validate_redirect_uri(uri: str) -> None:
    """Ensure ``uri`` is on the configured allowlist.

    Raises :class:`ValueError` when the redirect URI is not permitted,
    guarding against open-redirect / token-exfiltration attacks.
    """
    if uri not in settings.allowed_redirect_uris_list:
        raise ValueError(f"redirect_uri {uri!r} is not on the allowlist.")


def build_authorize_url() -> str:
    """Return the LinkedIn consent-screen URL.

    Raises RuntimeError if credentials are not configured and ValueError if
    the configured redirect URI is not on the allowlist.
    """
    if not settings.auth_configured:
        raise RuntimeError(
            "LinkedIn client credentials are not configured."
        )
    validate_redirect_uri(settings.linkedin_redirect_uri)
    state = secrets.token_urlsafe(16)
    tokens.state = state
    params = {
        "response_type": "code",
        "client_id": settings.linkedin_client_id,
        "redirect_uri": settings.linkedin_redirect_uri,
        "state": state,
        "scope": " ".join(settings.linkedin_scopes_list),
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(
    code: str, state: str
) -> dict[str, Any]:
    """Exchange an authorization code for access + refresh tokens.

    Returns the token response dict.  Raises on mismatched state or
    HTTP error.
    """
    if state != tokens.state:
        raise ValueError("OAuth state mismatch — possible CSRF.")
    validate_redirect_uri(settings.linkedin_redirect_uri)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ACCESS_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.linkedin_redirect_uri,
                "client_id": settings.linkedin_client_id,
                "client_secret": settings.linkedin_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _raise_for_status(resp)
    data: dict[str, Any] = resp.json()
    tokens.access_token = data["access_token"]
    tokens.refresh_token = data.get("refresh_token", "")
    tokens.expires_at = time.time() + float(data.get("expires_in", 0))
    return data


async def refresh_access_token() -> dict[str, Any]:
    """Use the stored refresh token to obtain a new access token."""
    if not tokens.refresh_token:
        raise RuntimeError("No refresh token available.")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ACCESS_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": settings.linkedin_client_id,
                "client_secret": settings.linkedin_client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _raise_for_status(resp)
    data: dict[str, Any] = resp.json()
    tokens.access_token = data["access_token"]
    tokens.refresh_token = data.get("refresh_token", tokens.refresh_token)
    tokens.expires_at = time.time() + float(data.get("expires_in", 0))
    return data


# ---------------------------------------------------------------------------
# LinkedIn API wrappers
# ---------------------------------------------------------------------------

def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {tokens.access_token}",
        "Content-Type": "application/json",
    }


async def get_profile() -> dict[str, Any]:
    """Fetch the authenticated member's profile (OpenID Connect userinfo)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/userinfo", headers=_auth_headers()
        )
        _raise_for_status(resp)
    result: dict[str, Any] = resp.json()
    return result


async def share_content(
    text: str, visibility: str = "PUBLIC"
) -> dict[str, Any]:
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
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/ugcPosts",
            json=payload,
            headers=_auth_headers(),
        )
        _raise_for_status(resp)
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
