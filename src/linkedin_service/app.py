"""FastAPI application — LinkedIn API service for fleet agents."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse

from . import auth
from .config import settings

app = FastAPI(
    title="robotsix-linkedin",
    version="0.1.0",
    description=(
        "LinkedIn API service for fleet agents — "
        "OAuth 2.0 auth, reads, operator-gated writes."
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
                "Set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET."
            ),
        )
    url = auth.build_authorize_url()
    return RedirectResponse(url=url)


@app.get("/auth/callback", tags=["auth"])
async def auth_callback(
    code: str = Query(...), state: str = Query(...)
) -> dict[str, Any]:
    """Handle the OAuth redirect from LinkedIn — exchange code for tokens."""
    try:
        token_data = await auth.exchange_code(code, state)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=str(exc)
        ) from exc
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


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

def _require_auth() -> None:
    if not auth.tokens.access_token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Call /auth/login first.",
        )


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


# ---------------------------------------------------------------------------
# Write endpoints (operator-gated)
# ---------------------------------------------------------------------------

@app.post("/share", tags=["write"])
async def create_share(
    text: str = Query(..., description="Share text content"),
    visibility: str = Query(
        "PUBLIC", description="PUBLIC or CONNECTIONS"
    ),
    confirmation_token: str | None = Query(
        None,
        description=(
            "Operator confirmation token. "
            "Required when require_operator_confirmation is True."
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
                "message": (
                    "Re-submit this request with the "
                    "confirmation_token to execute."
                ),
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
