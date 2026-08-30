"""Application configuration loaded from environment variables."""

from __future__ import annotations

import re

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All configuration is sourced from env vars (or a .env file in dev).

    When real LinkedIn app credentials are not yet available the service
    still boots and /health returns 200 — the auth layer is stubbed.
    """

    # --- LinkedIn OAuth 2.0 ---
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_redirect_uri: str = "http://localhost:8000/auth/callback"

    # Allowlist of redirect URIs the OAuth flow may use, in addition to
    # linkedin_redirect_uri (which is always allowed). Space- or
    # comma-separated. Any redirect URI not on the allowlist is rejected
    # to prevent open-redirect / token-exfiltration via a tampered value.
    linkedin_allowed_redirect_uris: str = ""

    # Scopes requested during the consent screen.
    # openid + profile + email are the minimum for Sign In with LinkedIn.
    # w_member_social is needed for posting / sharing.
    linkedin_scopes: str = "openid profile email w_member_social"

    # Path to the file where OAuth access/refresh tokens are persisted.
    # Kept OUTSIDE the repository so tokens survive restarts without being
    # committed. Written 0600 inside a 0700 directory; token values are
    # never logged. Set to an empty string to disable on-disk persistence.
    linkedin_token_file: str = "~/.config/linkedin-service/tokens.json"

    # --- Service ---
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Operator confirmation ---
    # When True, write endpoints require an explicit confirmation token
    # (issued by the operator) before the API call is forwarded to LinkedIn.
    require_operator_confirmation: bool = True

    model_config = {"env_prefix": "LINKEDIN_", "env_file": ".env", "extra": "ignore"}

    # Derived helpers -------------------------------------------------------

    @property
    def linkedin_scopes_list(self) -> list[str]:
        return self.linkedin_scopes.split()

    @property
    def allowed_redirect_uris_list(self) -> list[str]:
        """Redirect URIs permitted by the OAuth flow.

        Always includes ``linkedin_redirect_uri`` plus any extras declared
        in ``linkedin_allowed_redirect_uris`` (order preserved, deduped).
        """
        extras = [u for u in re.split(r"[,\s]+", self.linkedin_allowed_redirect_uris) if u]
        uris: list[str] = []
        for uri in [self.linkedin_redirect_uri, *extras]:
            if uri and uri not in uris:
                uris.append(uri)
        return uris

    @property
    def auth_configured(self) -> bool:
        """Return True when real LinkedIn credentials are present."""
        return bool(self.linkedin_client_id and self.linkedin_client_secret)


settings = Settings()
