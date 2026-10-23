"""Organization / Company Page reads.

Reading an organization's Company Page requires LinkedIn's Organization
APIs (organizationAcls / organizations), which are gated behind the
Community Management API access request plus one of the Organization
scopes below. These scopes must be present on a SEPARATE org app's OAuth
token (requested via ``linkedin_org_scopes`` at consent time and
re-authenticated once LinkedIn approves the request), stored in its own
token store so the personal app's token is never touched. Without them
LinkedIn rejects the calls with a generic 403, so we fail early with a
clear, actionable explanation instead.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from .org import _org_auth_headers
from .tokens import API_BASE, _retry_send

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
        resp = await _retry_send(
            client,
            "GET",
            f"{API_BASE}/organizationAcls",
            params=params,
            headers=_org_auth_headers(),
        )
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
        resp = await _retry_send(
            client,
            "GET",
            f"{API_BASE}/organizations/{organization_id}",
            params=params,
            headers=_org_auth_headers(),
        )
    org: dict[str, Any] = resp.json()
    return {
        "id": org.get("id"),
        "name": org.get("localizedName"),
        "vanity_name": org.get("vanityName"),
        "logo": _logo_url(org),
        "organization": org,
    }
