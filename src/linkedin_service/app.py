"""FastAPI application — LinkedIn API service for fleet agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from robotsix_config import (
    InvalidConfigError,
    apply_update,
    load_config,
    read_versions,
    rollback,
)

from . import auth
from .config import Settings, config_schema_json, settings

app = FastAPI(
    title="robotsix-linkedin",
    version="0.1.0",
    description=(
        "LinkedIn API service for fleet agents — OAuth 2.0 auth, reads, operator-gated writes."
    ),
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["infra"])
async def health() -> dict[str, Any]:
    """Liveness probe."""
    return {"status": "ok", "auth_configured": settings.auth_configured}


# ---------------------------------------------------------------------------
# Chat skill
# ---------------------------------------------------------------------------

CHAT_SKILL_PATH = Path("chat-skill.md")


@app.get("/chat-skill", tags=["infra"])
async def chat_skill() -> PlainTextResponse:
    """Return the SKILL.md document describing this service to chat agents."""
    try:
        content = CHAT_SKILL_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"chat-skill.md not found: {exc}",
        ) from exc
    return PlainTextResponse(content, media_type="text/markdown")


# ---------------------------------------------------------------------------
# Settings panel
# ---------------------------------------------------------------------------


@app.get("/config", tags=["config"])
async def get_config() -> dict[str, Any]:
    """Return the current configuration (secrets are masked)."""
    return settings.model_dump()


class _ConfigUpdate(BaseModel):
    """Partial config update — only supplied fields are changed."""

    linkedin_client_id: str | None = Field(
        default=None, description="LinkedIn app client ID (secret)."
    )
    linkedin_client_secret: str | None = Field(
        default=None, description="LinkedIn app client secret (secret)."
    )
    linkedin_redirect_uri: str | None = Field(
        default=None, description="OAuth redirect URI."
    )
    linkedin_allowed_redirect_uris: str | None = Field(
        default=None,
        description="Space- or comma-separated extra redirect URIs.",
    )
    linkedin_scopes: str | None = Field(
        default=None, description="Space-separated scope list."
    )
    linkedin_token_file: str | None = Field(
        default=None, description="Token persistence path (outside the repo)."
    )
    linkedin_org_client_id: str | None = Field(
        default=None, description="Dedicated org-app client ID (secret)."
    )
    linkedin_org_client_secret: str | None = Field(
        default=None, description="Dedicated org-app client secret (secret)."
    )
    linkedin_org_redirect_uri: str | None = Field(
        default=None, description="Org-app OAuth redirect URI."
    )
    linkedin_org_scopes: str | None = Field(
        default=None, description="Org-app scope list."
    )
    linkedin_org_token_file: str | None = Field(
        default=None, description="Org token persistence path (outside the repo)."
    )
    host: str | None = Field(default=None, description="Bind host.")
    port: int | None = Field(default=None, description="Bind port.")
    require_operator_confirmation: bool | None = Field(
        default=None, description="Require confirmation for writes."
    )


def _refresh_settings() -> None:
    """Reload the live ``settings`` singleton from the config file in place.

    ``auth.py`` and other modules imported ``settings`` by reference, so an
    in-place copy of the freshly loaded values makes a persisted change
    visible to them without a reload.
    """
    fresh = load_config(Settings)
    for name in Settings.model_fields:
        setattr(settings, name, getattr(fresh, name))


@app.put("/config", tags=["config"])
async def put_config(body: _ConfigUpdate) -> dict[str, Any]:
    """Update configuration and persist to the config file.

    Only fields present in the request body are changed; omitted fields
    keep their current values. Secret fields accept plain strings; a masked
    or empty value leaves the stored secret unchanged. Each write records a
    new config version.
    """
    updates = body.model_dump(exclude_none=True)
    try:
        _merged, changed_keys, version = apply_update(Settings, updates)
    except InvalidConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _refresh_settings()
    return {"status": "ok", "version": version, "changed_keys": changed_keys}


@app.get("/config/versions", tags=["config"])
async def get_config_versions() -> dict[str, Any]:
    """Return the recorded config version history, newest first."""
    versions = read_versions()
    versions.reverse()  # read_versions returns oldest-first.
    return {"versions": versions}


class _RollbackRequest(BaseModel):
    """Rollback request — the config version to restore."""

    version: int = Field(description="Config version to restore as a new version.")


@app.post("/config/rollback", tags=["config"])
async def rollback_config(body: _RollbackRequest) -> dict[str, Any]:
    """Restore an earlier config version as a new version.

    The history is append-only: rolling back writes a new entry whose values
    match the target version. Secrets are carried forward from the live
    config, never restored from history.
    """
    try:
        _restored, changed_keys, version = rollback(Settings, body.version)
    except InvalidConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _refresh_settings()
    return {"status": "ok", "version": version, "changed_keys": changed_keys}


@app.get("/config/schema", tags=["config"])
async def get_config_schema() -> dict[str, Any]:
    """Return the JSON Schema for the configuration model."""
    import json

    return json.loads(config_schema_json())  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# OAuth 2.0
# ---------------------------------------------------------------------------


@app.get("/auth/login", tags=["auth"])
async def auth_login() -> RedirectResponse:
    """Redirect the operator to LinkedIn's consent screen.

    Returns 503 when LinkedIn credentials are not yet configured.
    """
    if not settings.auth_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "LinkedIn client credentials not configured. "
                "Set them via PUT /config or in config/config.json."
            ),
        )
    url = auth.build_authorize_url()
    return RedirectResponse(url=url)


@app.get("/auth/callback", tags=["auth"])
async def auth_callback(code: str = Query(...), state: str = Query(...)) -> dict[str, Any]:
    """Handle the OAuth redirect from LinkedIn — exchange code for tokens."""
    try:
        token_data = await auth.exchange_code(code, state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Token exchange failed: {exc}",
        ) from exc
    return {
        "message": "Authentication successful.",
        "token_type": token_data.get("token_type"),
        "expires_in": token_data.get("expires_in"),
        "scope": token_data.get("scope"),
    }


@app.get("/auth/org/login", tags=["auth"])
async def org_auth_login() -> RedirectResponse:
    """Redirect the operator to LinkedIn's consent screen for the org app.

    The org app has its own client credentials, scopes and token store, so
    org reads never touch the personal app's token. Returns 503 when the org
    app credentials are not yet configured.
    """
    if not settings.org_auth_configured:
        raise HTTPException(
            status_code=503,
            detail=(
                "LinkedIn org app credentials not configured. Set "
                "linkedin_org_client_id / linkedin_org_client_secret via PUT "
                "/config or in config/config.json."
            ),
        )
    url = auth.build_org_authorize_url()
    return RedirectResponse(url=url)


@app.get("/auth/org/callback", tags=["auth"])
async def org_auth_callback(
    code: str = Query(...), state: str = Query(...)
) -> dict[str, Any]:
    """Handle the org app's OAuth redirect — exchange code for org tokens."""
    try:
        token_data = await auth.exchange_org_code(code, state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Org token exchange failed: {exc}",
        ) from exc
    return {
        "message": "Organization app authentication successful.",
        "token_type": token_data.get("token_type"),
        "expires_in": token_data.get("expires_in"),
        "scope": token_data.get("scope"),
    }


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


def _require_auth() -> None:
    if not auth.tokens.access_token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Call /auth/login first.",
        )


def _require_org_auth() -> None:
    if not auth.org_tokens.access_token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated for organization reads. Complete /auth/org/login first.",
        )


def _handle_linkedin_error(exc: Exception) -> NoReturn:
    """Translate LinkedIn-side errors into helpful HTTP responses.

    A missing/unconfigured org app or missing org scope is surfaced as a
    clear 403 rather than an opaque 502, and upstream 403s (e.g. LinkedIn
    rejecting an org call despite a configured scope) explain what is needed
    instead of failing silently. Always raises.
    """
    if isinstance(exc, auth.OrgAppNotConfiguredError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, auth.LinkedInScopeMissingError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, auth.LinkedInAPIError) and exc.status_code == 403:
        raise HTTPException(
            status_code=403,
            detail=(
                "LinkedIn rejected the organization request (403). Community "
                "Management API access plus an Organization scope is required "
                "on the org app's token; ensure linkedin_org_scopes includes "
                "r_organization_social or rw_organization_admin, then "
                "re-authenticate via /auth/org/login."
            ),
        ) from exc
    raise HTTPException(
        status_code=502,
        detail=f"LinkedIn API error: {exc}",
    ) from exc


@app.get("/me", tags=["read"])
async def me() -> dict[str, Any]:
    """Return the authenticated member's profile."""
    _require_auth()
    try:
        return await auth.get_profile()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LinkedIn API error: {exc}",
        ) from exc


@app.get("/organizations", tags=["read"])
async def list_organizations() -> dict[str, Any]:
    """List Company Pages the authenticated member administers (read-only)."""
    _require_org_auth()
    try:
        return await auth.list_organizations()
    except Exception as exc:
        _handle_linkedin_error(exc)


@app.get("/organizations/{organization_id}", tags=["read"])
async def get_organization(organization_id: str) -> dict[str, Any]:
    """Fetch a single Company Page's details by LinkedIn organization id."""
    _require_org_auth()
    try:
        return await auth.get_organization(organization_id)
    except Exception as exc:
        _handle_linkedin_error(exc)


# ---------------------------------------------------------------------------
# Write endpoints (operator-gated)
# ---------------------------------------------------------------------------


@app.post("/share", tags=["write"])
async def create_share(
    text: str = Query(..., description="Share text content"),
    visibility: str = Query("PUBLIC", description="PUBLIC or CONNECTIONS"),
    confirmation_token: str | None = Query(
        None,
        description=(
            "Operator confirmation token. Required when require_operator_confirmation is True."
        ),
    ),
) -> dict[str, Any]:
    """Create a share / post on LinkedIn.

    **State-mutating** — requires an operator confirmation token when
    ``require_operator_confirmation`` is enabled (the default).
    """
    _require_auth()
    if settings.require_operator_confirmation:
        if not confirmation_token:
            token = auth.generate_confirmation_token(
                {
                    "action": "share",
                    "text": text,
                    "visibility": visibility,
                }
            )
            return {
                "status": "confirmation_required",
                "confirmation_token": token,
                "message": ("Re-submit this request with the confirmation_token to execute."),
            }
        payload = auth.consume_confirmation_token(confirmation_token)
        if payload is None:
            raise HTTPException(
                status_code=400,
                detail="Invalid or expired confirmation token.",
            )
    try:
        result = await auth.share_content(text, visibility)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LinkedIn API error: {exc}",
        ) from exc
    return {"status": "posted", "result": result}
