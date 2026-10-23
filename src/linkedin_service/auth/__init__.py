"""LinkedIn OAuth 2.0 helper — authorization-code grant flow.

When real credentials are not configured the module exposes stub
endpoints so the service still boots and /health passes.

The implementation is split by responsibility:

- :mod:`.tokens` — endpoints, HTTP error contract, token stores,
  confirmation tokens and the shared app-agnostic OAuth flow;
- :mod:`.personal` — the personal-account app flow and member API calls;
- :mod:`.org` — the dedicated org-app (Community Management API) flow;
- :mod:`.organizations` — Company Page reads using the org token.

Every public name is re-exported here so ``from linkedin_service import
auth`` call sites keep working unchanged.
"""

from __future__ import annotations

import httpx

from ..config import settings
from .org import (
    ORG_APP,
    _org_auth_headers,
    build_org_authorize_url,
    exchange_org_code,
    refresh_org_access_token,
    validate_org_redirect_uri,
)
from .organizations import (
    ORG_READ_SCOPES,
    LinkedInScopeMissingError,
    OrgAppNotConfiguredError,
    _logo_url,
    _require_org_scope,
    get_organization,
    list_organizations,
)
from .personal import (
    PERSONAL_APP,
    _auth_headers,
    build_authorize_url,
    exchange_code,
    get_profile,
    refresh_access_token,
    share_content,
    validate_redirect_uri,
)
from .tokens import (
    ACCESS_TOKEN_URL,
    API_BASE,
    AUTHORIZE_URL,
    LinkedInAPIError,
    OAuthApp,
    TokenStore,
    _app_auth_headers,
    _build_app_authorize_url,
    _consume_state,
    _exchange_app_code,
    _pending_confirmations,
    _refresh_app_access_token,
    _request_app_token,
    _retry_send,
    _secure_store,
    _validate_app_redirect_uri,
    consume_confirmation_token,
    generate_confirmation_token,
    org_tokens,
    tokens,
)

__all__ = [
    "ACCESS_TOKEN_URL",
    "API_BASE",
    "AUTHORIZE_URL",
    "ORG_APP",
    "ORG_READ_SCOPES",
    "PERSONAL_APP",
    "LinkedInAPIError",
    "LinkedInScopeMissingError",
    "OAuthApp",
    "OrgAppNotConfiguredError",
    "TokenStore",
    "_app_auth_headers",
    "_auth_headers",
    "_build_app_authorize_url",
    "_consume_state",
    "_exchange_app_code",
    "_logo_url",
    "_org_auth_headers",
    "_pending_confirmations",
    "_refresh_app_access_token",
    "_request_app_token",
    "_require_org_scope",
    "_retry_send",
    "_secure_store",
    "_validate_app_redirect_uri",
    "build_authorize_url",
    "build_org_authorize_url",
    "consume_confirmation_token",
    "exchange_code",
    "exchange_org_code",
    "generate_confirmation_token",
    "get_organization",
    "get_profile",
    "httpx",
    "list_organizations",
    "org_tokens",
    "refresh_access_token",
    "refresh_org_access_token",
    "settings",
    "share_content",
    "tokens",
    "validate_org_redirect_uri",
    "validate_redirect_uri",
]
