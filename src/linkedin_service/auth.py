"""LinkedIn OAuth 2.0 helper — authorization-code grant flow.

When real credentials are not configured the module exposes stub
endpoints so the service still boots and /health passes.
"""

from __future__ import annotations

import json
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
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
    """Token storage backed by an on-disk file outside the repo.

    Access/refresh tokens are loaded on startup and re-persisted whenever
    they change, so operators do not have to repeat the OAuth consent flow
    after a restart. The file is written 0600 inside a 0700 directory and
    token values are never logged.
    """

    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0  # unix timestamp
    state: str = ""

    def _persisted_dict(self) -> dict[str, Any]:
        """Return the subset of fields that survive a restart.

        ``state`` is a per-flow CSRF nonce and is deliberately excluded.
        """
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }

    def save(self, path: str | None = None) -> None:
        """Persist tokens to disk (0600 file inside a 0700 directory).

        No-op when no token file is configured. Token values are never
        written to logs.
        """
        target = path if path is not None else settings.linkedin_token_file
        if not target:
            return
        file_path = Path(target).expanduser()
        parent = file_path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(parent, 0o700)
        fd = os.open(
            str(file_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self._persisted_dict(), fh)
        os.chmod(file_path, 0o600)

    def load(self, path: str | None = None) -> None:
        """Load persisted tokens on startup. No-op when the file is absent."""
        target = path if path is not None else settings.linkedin_token_file
        if not target:
            return
        file_path = Path(target).expanduser()
        if not file_path.exists():
            return
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except ValueError, OSError:
            return
        self.access_token = data.get("access_token", "")
        self.refresh_token = data.get("refresh_token", "")
        self.expires_at = float(data.get("expires_at", 0.0))


tokens = TokenStore()
# Load any previously persisted tokens so a restart does not force the
# operator to redo the OAuth consent flow.
tokens.load()

# Second, fully independent token store for the dedicated org LinkedIn app
# (Community Management API). Org reads authenticate with THIS token, never
# the personal one, so the two OAuth flows coexist without clobbering each
# other.
org_tokens = TokenStore()
org_tokens.load(settings.linkedin_org_token_file)

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
        raise RuntimeError("LinkedIn client credentials are not configured.")
    validate_redirect_uri(settings.linkedin_redirect_uri)
    state = secrets.token_urlsafe(16)
    tokens.state = state
    params = {
        "response_type": "code",
        "client_id": settings.linkedin_client_id.get_secret_value(),
        "redirect_uri": settings.linkedin_redirect_uri,
        "state": state,
        "scope": " ".join(settings.linkedin_scopes_list),
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str, state: str) -> dict[str, Any]:
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
                "client_id": settings.linkedin_client_id.get_secret_value(),
                "client_secret": settings.linkedin_client_secret.get_secret_value(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _raise_for_status(resp)
    data: dict[str, Any] = resp.json()
    tokens.access_token = data["access_token"]
    tokens.refresh_token = data.get("refresh_token", "")
    tokens.expires_at = time.time() + float(data.get("expires_in", 0))
    tokens.save()
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
    tokens.save()
    return data


# ---------------------------------------------------------------------------
# Org-app OAuth flow (dedicated LinkedIn app for Community Management API)
# ---------------------------------------------------------------------------
#
# The org app has its own client credentials, redirect URI, scopes and token
# store, and its own consent/callback routes (/auth/org/login,
# /auth/org/callback). It is deliberately isolated from the personal app's
# flow so neither token store overwrites the other.


def validate_org_redirect_uri(uri: str) -> None:
    """Ensure ``uri`` is on the org-app redirect allowlist."""
    if uri not in settings.org_allowed_redirect_uris_list:
        raise ValueError(f"redirect_uri {uri!r} is not on the org allowlist.")


def build_org_authorize_url() -> str:
    """Return the LinkedIn consent-screen URL for the org app.

    Raises RuntimeError if the org app credentials are not configured and
    ValueError if the configured redirect URI is not on the allowlist.
    """
    if not settings.org_auth_configured:
        raise RuntimeError("LinkedIn org app credentials are not configured.")
    validate_org_redirect_uri(settings.linkedin_org_redirect_uri)
    state = secrets.token_urlsafe(16)
    org_tokens.state = state
    params = {
        "response_type": "code",
        "client_id": settings.linkedin_org_client_id.get_secret_value(),
        "redirect_uri": settings.linkedin_org_redirect_uri,
        "state": state,
        "scope": " ".join(settings.linkedin_org_scopes_list),
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


async def exchange_org_code(code: str, state: str) -> dict[str, Any]:
    """Exchange an org-app authorization code for tokens.

    Tokens land in ``org_tokens`` (never ``tokens``). Raises on mismatched
    state or HTTP error.
    """
    if state != org_tokens.state:
        raise ValueError("OAuth state mismatch — possible CSRF.")
    validate_org_redirect_uri(settings.linkedin_org_redirect_uri)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ACCESS_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.linkedin_org_redirect_uri,
                "client_id": settings.linkedin_org_client_id.get_secret_value(),
                "client_secret": settings.linkedin_org_client_secret.get_secret_value(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _raise_for_status(resp)
    data: dict[str, Any] = resp.json()
    org_tokens.access_token = data["access_token"]
    org_tokens.refresh_token = data.get("refresh_token", "")
    org_tokens.expires_at = time.time() + float(data.get("expires_in", 0))
    org_tokens.save(settings.linkedin_org_token_file)
    return data


async def refresh_org_access_token() -> dict[str, Any]:
    """Use the stored org refresh token to obtain a new org access token."""
    if not org_tokens.refresh_token:
        raise RuntimeError("No org refresh token available.")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ACCESS_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": org_tokens.refresh_token,
                "client_id": settings.linkedin_org_client_id.get_secret_value(),
                "client_secret": settings.linkedin_org_client_secret.get_secret_value(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _raise_for_status(resp)
    data: dict[str, Any] = resp.json()
    org_tokens.access_token = data["access_token"]
    org_tokens.refresh_token = data.get("refresh_token", org_tokens.refresh_token)
    org_tokens.expires_at = time.time() + float(data.get("expires_in", 0))
    org_tokens.save(settings.linkedin_org_token_file)
    return data


# ---------------------------------------------------------------------------
# LinkedIn API wrappers
# ---------------------------------------------------------------------------


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {tokens.access_token}",
        "Content-Type": "application/json",
    }


def _org_auth_headers() -> dict[str, str]:
    """Auth headers for the dedicated org LinkedIn app's token."""
    return {
        "Authorization": f"Bearer {org_tokens.access_token}",
        "Content-Type": "application/json",
    }


async def get_profile() -> dict[str, Any]:
    """Fetch the authenticated member's profile (OpenID Connect userinfo)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/userinfo", headers=_auth_headers())
        _raise_for_status(resp)
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


# ---------------------------------------------------------------------------
# Organization / Company Page reads
# ---------------------------------------------------------------------------
#
# Reading an organization's Company Page requires LinkedIn's Organization
# APIs (organizationAcls / organizations), which are gated behind the
# Community Management API access request plus one of the Organization
# scopes below. These scopes must be present on a SEPARATE org app's OAuth
# token (requested via ``linkedin_org_scopes`` at consent time and
# re-authenticated once LinkedIn approves the request), stored in its own
# token store so the personal app's token is never touched. Without them
# LinkedIn rejects the calls with a generic 403, so we fail early with a
# clear, actionable explanation instead.

ORG_READ_SCOPES = frozenset({"r_organization_social", "rw_organization_admin"})


class OrgAppNotConfiguredError(RuntimeError):
    """Raised when the dedicated org LinkedIn app is not configured.

    Surfaced to callers as a 403 explaining that Community Management API
    access plus an org app with Organization scopes is required, rather than
    an opaque upstream failure.
    """


class LinkedInScopeMissingError(RuntimeError):
    """Raised when the org scope is not present on the org token/consent.

    Surfaced to callers as a 403 explaining that Community Management API
    access plus an Organization scope is required, rather than an opaque
    upstream failure.
    """


def _require_org_scope() -> None:
    """Guard organization reads behind a fully-configured org app.

    Raises :class:`OrgAppNotConfiguredError` when the dedicated org app
    credentials are absent, and :class:`LinkedInScopeMissingError` when
    ``linkedin_org_scopes`` does not include one of the Organization scopes.
    """
    if not settings.org_auth_configured:
        raise OrgAppNotConfiguredError(
            "Cannot read LinkedIn organizations: the dedicated org LinkedIn "
            "app is not configured. Company Page reads require Community "
            "Management API access (requested and approved by LinkedIn) using "
            "a separate org app. Set linkedin_org_client_id and "
            "linkedin_org_client_secret, then complete /auth/org/login once "
            "to obtain an org token."
        )
    if not ORG_READ_SCOPES.intersection(settings.linkedin_org_scopes_list):
        raise LinkedInScopeMissingError(
            "Cannot read LinkedIn organizations: the org app's token consent "
            "does not include an Organization scope. Community Management API "
            "access must be approved by LinkedIn and an org scope "
            "(r_organization_social or rw_organization_admin) must be present "
            "in linkedin_org_scopes, then the operator must re-authenticate "
            "via /auth/org/login."
        )


def _logo_url(org: dict[str, Any]) -> str | None:
    """Extract the logo CDN URL from an org's ``logoV2`` decoration.

    On the real API ``logoV2.original`` is the image **URN string**, and the
    resolved image object sits at ``logoV2.original~`` (carrying a ``url``,
    or an ``elements`` list whose entries expose a ``url`` / ``identifiers``
    URL). We read the decorated ``original~`` only, so a raw URN string never
    crashes extraction. Returns None when not decorated.
    """
    logo_v2 = org.get("logoV2")
    if not isinstance(logo_v2, dict):
        return None
    resolved = logo_v2.get("original~")
    if not isinstance(resolved, dict):
        return None
    url = resolved.get("url")
    if isinstance(url, str) and url:
        return url
    for element in resolved.get("elements") or []:
        if not isinstance(element, dict):
            continue
        url = element.get("url")
        if isinstance(url, str) and url:
            return url
        for identifier in element.get("identifiers") or []:
            if not isinstance(identifier, dict):
                continue
            candidate = identifier.get("identifier")
            if isinstance(candidate, str) and candidate.startswith("http"):
                return candidate
    return None


async def list_organizations() -> dict[str, Any]:
    """List Company Pages the authenticated member administers (read-only).

    Calls ``organizationAcls`` filtered to ADMINISTRATOR role assignments and
    resolves each organization's id, name, vanity name and logo.
    """
    _require_org_scope()
    params = {
        "q": "roleAssignee",
        "role": "ADMINISTRATOR",
        "projection": "(elements*(organization~(id,localizedName,vanityName,logoV2)))",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/organizationAcls",
            params=params,
            headers=_org_auth_headers(),
        )
        _raise_for_status(resp)
    data: dict[str, Any] = resp.json()
    companies: list[dict[str, Any]] = []
    for element in data.get("elements") or []:
        org = element.get("organization") or {}
        companies.append(
            {
                "id": org.get("id"),
                "name": org.get("localizedName"),
                "vanity_name": org.get("vanityName"),
                "logo": _logo_url(org),
            }
        )
    return {"elements": companies}


async def get_organization(organization_id: str) -> dict[str, Any]:
    """Fetch a single Company Page's details by LinkedIn organization id."""
    _require_org_scope()
    params = {"projection": "(id,localizedName,vanityName,logoV2)"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/organizations/{organization_id}",
            params=params,
            headers=_org_auth_headers(),
        )
        _raise_for_status(resp)
    org: dict[str, Any] = resp.json()
    return {
        "id": org.get("id"),
        "name": org.get("localizedName"),
        "vanity_name": org.get("vanityName"),
        "logo": _logo_url(org),
        "organization": org,
    }
