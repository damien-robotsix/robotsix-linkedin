"""Application configuration.

Settings are loaded from a single JSON config file via ``robotsix-config``.
There is no environment-variable overlay — the file is the sole source of
truth.  Operators edit it through the ``GET /config`` / ``PUT /config``
Settings panel endpoints, or by mounting a file at the path declared by the
``robotsix.deploy.config-target`` compose label.

Secret fields (``linkedin_client_id``, ``linkedin_client_secret``) use
:class:`pydantic.SecretStr` so they are masked in API responses and marked
``writeOnly`` in the JSON Schema.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, SecretStr
from robotsix_config import (
    config_schema_json as _config_schema_json,
)
from robotsix_config import (
    load_config,
)


class Settings(BaseModel):
    """Configuration sourced from one JSON file — no env overlay."""

    # --- LinkedIn OAuth 2.0 ---
    linkedin_client_id: SecretStr = SecretStr("")
    linkedin_client_secret: SecretStr = SecretStr("")
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
        extras = [
            u
            for u in re.split(r"[,\s]+", self.linkedin_allowed_redirect_uris)
            if u
        ]
        uris: list[str] = []
        for uri in [self.linkedin_redirect_uri, *extras]:
            if uri and uri not in uris:
                uris.append(uri)
        return uris

    @property
    def auth_configured(self) -> bool:
        """Return True when real LinkedIn credentials are present."""
        return bool(
            self.linkedin_client_id.get_secret_value()
            and self.linkedin_client_secret.get_secret_value()
        )


def config_schema_json() -> str:
    """Return the JSON Schema for :class:`Settings` as a string."""
    return _config_schema_json(Settings)


# Load the singleton from the one config file.
settings: Settings = load_config(Settings)
