"""Org-app OAuth flow (dedicated LinkedIn app for Community Management API).

The org app has its own client credentials, redirect URI, scopes and token
store, and its own consent/callback routes (/auth/org/login,
/auth/org/callback). It is deliberately isolated from the personal app's
flow so neither token store overwrites the other.
"""

from __future__ import annotations

from typing import Any

from ..config import settings
from .tokens import (
    OAuthApp,
    _app_auth_headers,
    _build_app_authorize_url,
    _exchange_app_code,
    _refresh_app_access_token,
    _validate_app_redirect_uri,
    org_tokens,
)

# Dedicated org LinkedIn app (Community Management API), isolated from the
# personal app so neither token store overwrites the other.
ORG_APP = OAuthApp(
    tokens=org_tokens,
    configured=lambda: settings.org_auth_configured,
    client_id=lambda: settings.linkedin_org_client_id.get_secret_value(),
    client_secret=lambda: settings.linkedin_org_client_secret.get_secret_value(),
    redirect_uri=lambda: settings.linkedin_org_redirect_uri,
    allowed_redirect_uris=lambda: settings.org_allowed_redirect_uris_list,
    scopes=lambda: settings.linkedin_org_scopes_list,
    token_file=lambda: settings.linkedin_org_token_file,
    not_configured_message="LinkedIn org app credentials are not configured.",
    allowlist_label="org allowlist",
    refresh_label="org refresh token",
)


def validate_org_redirect_uri(uri: str) -> None:
    """Ensure ``uri`` is on the org-app redirect allowlist."""
    _validate_app_redirect_uri(ORG_APP, uri)


def build_org_authorize_url() -> str:
    """Return the LinkedIn consent-screen URL for the org app.

    Raises RuntimeError if the org app credentials are not configured and
    ValueError if the configured redirect URI is not on the allowlist.
    """
    return _build_app_authorize_url(ORG_APP)


async def exchange_org_code(code: str, state: str) -> dict[str, Any]:
    """Exchange an org-app authorization code for tokens.

    Tokens land in ``org_tokens`` (never ``tokens``). Raises on mismatched
    state or HTTP error.
    """
    return await _exchange_app_code(ORG_APP, code, state)


async def refresh_org_access_token() -> dict[str, Any]:
    """Use the stored org refresh token to obtain a new org access token.

    Like :func:`~.personal.refresh_access_token`, this is deliberately
    manual and not wired into the request path.
    """
    return await _refresh_app_access_token(ORG_APP)


def _org_auth_headers() -> dict[str, str]:
    """Auth headers for the dedicated org LinkedIn app's token."""
    return _app_auth_headers(ORG_APP)
