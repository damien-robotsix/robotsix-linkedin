"""Token handling and shared OAuth plumbing for the LinkedIn apps.

Owns the LinkedIn OAuth/API endpoints, the HTTP error contract, the on-disk
token stores (personal and org), the one-time write-confirmation tokens, and
the app-agnostic authorization-code flow implementation that the personal
(:mod:`.personal`) and org (:mod:`.org`) flows wrap.
"""

from __future__ import annotations

import json
import secrets
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from robotsix_http import ExternalHTTPError, RetryClient
from robotsix_http.oauth import SecureTokenStore

from ..config import settings

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


async def _retry_send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request through robotsix-http's ``RetryClient``.

    Transient 5xx / connection errors are retried with backoff, consistently
    with the rest of the fleet. ``RetryClient`` gates POST/PATCH retries to
    pre-delivery (connection) failures, so token exchanges and the share
    write are never duplicated, while idempotent GET reads and token refresh
    retry freely. Any terminal HTTP error is re-mapped to
    :class:`LinkedInAPIError` to preserve the existing caller contract.
    """
    try:
        return await RetryClient(client).request(method, url, **kwargs)
    except ExternalHTTPError as exc:
        raise LinkedInAPIError(exc.status_code, exc.response.text) from exc
    except httpx.HTTPStatusError as exc:
        raise LinkedInAPIError(exc.response.status_code, exc.response.text) from exc


def _secure_store(path: str | None) -> SecureTokenStore[dict[str, Any]]:
    """Return the shared secure on-disk store for a persisted-token dict.

    Delegates the 0700-directory / 0600-file security posture, the
    empty-path-disables-persistence contract, and the missing/corrupt-file
    silent no-op to ``robotsix_http.oauth`` (the fleet-shared helpers), with
    the LinkedIn-specific JSON (de)serialization layered on top. ``~`` in the
    configured path is expanded so operator home-relative paths keep working.
    """
    expanded = str(Path(path).expanduser()) if path else path
    return SecureTokenStore(path=expanded, dumps=json.dumps, loads=json.loads)


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

        No-op when no token file is configured. The on-disk security
        posture (0700 directory, 0600 file, empty-path-disables contract)
        is owned by :class:`robotsix_http.oauth.SecureTokenStore`; this
        store only layers the LinkedIn-specific JSON serialization on top.
        Token values are never written to logs.
        """
        target = path if path is not None else settings.linkedin_token_file
        _secure_store(target).save(self._persisted_dict())

    def load(self, path: str | None = None) -> None:
        """Load persisted tokens on startup. No-op when the file is absent.

        A missing or corrupt on-disk payload degrades to a cold start
        (fields left untouched) rather than raising, courtesy of
        :class:`robotsix_http.oauth.SecureTokenStore`.
        """
        target = path if path is not None else settings.linkedin_token_file
        data = _secure_store(target).load()
        if data is None:
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


@dataclass(frozen=True)
class OAuthApp:
    """One LinkedIn OAuth app (personal or org) and the token store it owns.

    Settings-backed fields are zero-arg callables evaluated at call time so
    runtime config updates are honoured. The personal and org flows are
    each a thin wrapper around a shared implementation taking an
    :class:`OAuthApp`.
    """

    tokens: TokenStore
    configured: Callable[[], bool]
    client_id: Callable[[], str]
    client_secret: Callable[[], str]
    redirect_uri: Callable[[], str]
    allowed_redirect_uris: Callable[[], list[str]]
    scopes: Callable[[], list[str]]
    token_file: Callable[[], str]
    not_configured_message: str
    allowlist_label: str
    refresh_label: str


def _validate_app_redirect_uri(app: OAuthApp, uri: str) -> None:
    """Raise :class:`ValueError` unless ``uri`` is on ``app``'s allowlist."""
    if uri not in app.allowed_redirect_uris():
        raise ValueError(f"redirect_uri {uri!r} is not on the {app.allowlist_label}.")


def _build_app_authorize_url(app: OAuthApp) -> str:
    """Return the LinkedIn consent-screen URL for ``app``."""
    if not app.configured():
        raise RuntimeError(app.not_configured_message)
    redirect_uri = app.redirect_uri()
    _validate_app_redirect_uri(app, redirect_uri)
    state = secrets.token_urlsafe(16)
    app.tokens.state = state
    params = {
        "response_type": "code",
        "client_id": app.client_id(),
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": " ".join(app.scopes()),
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


async def _request_app_token(
    app: OAuthApp, grant: dict[str, str], default_refresh: str
) -> dict[str, Any]:
    """POST a token grant for ``app`` and persist the result in its store."""
    async with httpx.AsyncClient() as client:
        resp = await _retry_send(
            client,
            "POST",
            ACCESS_TOKEN_URL,
            data={
                **grant,
                "client_id": app.client_id(),
                "client_secret": app.client_secret(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    data: dict[str, Any] = resp.json()
    store = app.tokens
    store.access_token = data["access_token"]
    store.refresh_token = data.get("refresh_token", default_refresh)
    store.expires_at = time.time() + float(data.get("expires_in", 0))
    store.save(app.token_file())
    return data


def _consume_state(store: TokenStore, state: str) -> None:
    """Validate and burn the one-time OAuth ``state`` nonce held by ``store``.

    Rejects when no login flow is pending (empty stored state) so an
    attacker cannot pass ``state=`` before ``/auth/login`` was ever called
    (login-CSRF), compares in constant time, and clears the nonce once the
    check passes so it cannot be replayed.
    """
    expected = store.state
    if not expected or not secrets.compare_digest(state.encode("utf-8"), expected.encode("utf-8")):
        raise ValueError("OAuth state mismatch — possible CSRF.")
    store.state = ""


async def _exchange_app_code(app: OAuthApp, code: str, state: str) -> dict[str, Any]:
    """Exchange an authorization code for ``app``'s tokens."""
    _consume_state(app.tokens, state)
    redirect_uri = app.redirect_uri()
    _validate_app_redirect_uri(app, redirect_uri)
    grant = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    return await _request_app_token(app, grant, "")


async def _refresh_app_access_token(app: OAuthApp) -> dict[str, Any]:
    """Use ``app``'s stored refresh token to obtain a new access token."""
    refresh_token = app.tokens.refresh_token
    if not refresh_token:
        raise RuntimeError(f"No {app.refresh_label} available.")
    grant = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    return await _request_app_token(app, grant, refresh_token)


def _app_auth_headers(app: OAuthApp) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {app.tokens.access_token}",
        "Content-Type": "application/json",
    }
