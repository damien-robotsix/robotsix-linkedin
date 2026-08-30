"""Application configuration loaded from environment variables."""

from __future__ import annotations

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

    # Scopes requested during the consent screen.
    # openid + profile + email are the minimum for Sign In with LinkedIn.
    # w_member_social is needed for posting / sharing.
    linkedin_scopes: str = "openid profile email w_member_social"

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
        return [s.strip() for s in self.linkedin_scopes.split(",") if s.strip()]

    @property
    def auth_configured(self) -> bool:
        """Return True when real LinkedIn credentials are present."""
        return bool(self.linkedin_client_id and self.linkedin_client_secret)


settings = Settings()
