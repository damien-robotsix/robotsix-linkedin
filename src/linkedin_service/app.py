"""FastAPI application — LinkedIn API service for fleet agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel
from robotsix_config import dump_config

from . import auth
from .config import config_schema_json, settings

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

    linkedin_client_id: str | None = None
    linkedin_client_secret: str | None = None
    linkedin_redirect_uri: str | None = None
    linkedin_allowed_redirect_uris: str | None = None
    linkedin_scopes: str | None = None
    linkedin_token_file: str | None = None
    linkedin_org_client_id: str | None = None
    linkedin_org_client_secret: str | None = None
    linkedin_org_redirect_uri: str | None = None
    linkedin_org_scopes: str | None = None
    linkedin_org_token_file: str | None = None
    host: str | None = None
    port: int | None = None
    require_operator_confirmation: bool | None = None


@app.put("/config", tags=["config"])
async def put_config(body: _ConfigUpdate) -> dict[str, Any]:
    """Update configuration and persist to the config file.

    Only fields present in the request body are changed; omitted fields
    keep their current values. Secret fields accept plain strings.
    """
    updates = body.model_dump(exclude_none=True)

    # Convert plain-string secret fields to SecretStr.
    for key in (
        "linkedin_client_id",
        "linkedin_client_secret",
        "linkedin_org_client_id",
        "linkedin_org_client_secret",
    ):
        if key in updates:
            from pydantic import SecretStr

            updates[key] = SecretStr(updates[key])

    # Apply updates to the live settings object in-place so every module
    # that imported ``settings`` sees the change immediately.
    for key, value in updates.items():
        setattr(settings, key, value)

    # Persist to the config file.
    dump_config(settings)

    return {"status": "ok"}


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
