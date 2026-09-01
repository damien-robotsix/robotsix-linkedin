---
name: robotsix-linkedin
description: Drive the LinkedIn API service — read the authenticated profile and Company Pages and post operator-gated shares.
---

# Chat Skill — robotsix-linkedin

## Overview

LinkedIn API service for fleet agents. Provides OAuth 2.0 authentication,
profile reads, organization / Company Page reads, and operator-gated write
actions (posting / sharing).

Two independent LinkedIn apps are supported so their OAuth tokens never
clobber each other:

- the **personal app** authenticates `/me` and `/share`;
- a dedicated **org app** (Community Management API) authenticates the
  organization read endpoints.

## Endpoints

### Infra

| Method | Path      | Description          | Auth required |
|--------|-----------|----------------------|---------------|
| GET    | `/health` | Liveness probe       | No            |

### Config (Settings panel)

| Method | Path             | Description                                      | Auth required |
|--------|------------------|--------------------------------------------------|---------------|
| GET    | `/config`        | Current configuration (secrets masked)           | No            |
| PUT    | `/config`        | Update configuration and persist to config file  | No            |
| GET    | `/config/schema` | JSON Schema for the configuration model          | No            |

### Auth (OAuth 2.0 — 3-legged)

| Method | Path                  | Description                                                    | Auth required |
|--------|-----------------------|----------------------------------------------------------------|---------------|
| GET    | `/auth/login`         | Redirect operator to LinkedIn consent screen (personal app)    | No            |
| GET    | `/auth/callback`      | Personal-app OAuth redirect handler — exchanges code for token | No            |
| GET    | `/auth/org/login`     | Redirect operator to consent screen for the dedicated org app  | No            |
| GET    | `/auth/org/callback`  | Org-app OAuth redirect handler — exchanges code for org token  | No            |

> **Two apps:** the org app is a **separate LinkedIn application** with its
> own client id/secret, consent flow (`/auth/org/login` +
> `/auth/org/callback`) and token store. Run the org consent flow **once**
> per org app so `/organizations` gets a valid org token; the personal
> `/me` + `/share` flow is untouched.

### Read

| Method | Path                  | Description                                            | Auth required       |
|--------|-----------------------|--------------------------------------------------------|---------------------|
| GET    | `/me`                 | Authenticated member's profile (personal app token)    | Yes (personal app)  |
| GET    | `/organizations`      | List Company Pages the member administers (id, name, vanity name, logo) | Yes (org app) |
| GET    | `/organizations/{id}` | Fetch one Company Page's admin-visible details by organization id | Yes (org app) |

> **Organizations note:** `/organizations` and `/organizations/{id}`
> authenticate with the **org app's** token (`/auth/org/login`), not the
> personal token. They require the dedicated org app to be configured
> (`linkedin_org_client_id` / `linkedin_org_client_secret`) plus one
> Organization scope (`r_organization_social` or `rw_organization_admin`).
> If the org app is not configured, if the org scopes are missing, or if
> LinkedIn rejects the call (403), they return a clear **403** explaining
> what is needed — never a silent 500.

### Write (state-mutating — operator-gated)

| Method | Path     | Description                    | Auth required | Confirmation |
|--------|----------|--------------------------------|---------------|--------------|
| POST   | `/share` | Create a share / post on LinkedIn | Yes           | **Yes**      |

## Safety Rules

1. **Read endpoints** (`/me`, `/organizations`, `/organizations/{id}`) are
   safe to call without operator approval. Organization reads are read-only —
   they never mutate a Company Page.
2. **Write endpoints** (`/share`) are **state-mutating**. They require:
   - An authenticated session (valid OAuth token).
   - An **operator confirmation token** (issued on first call, consumed on second).
   - The two-call pattern: first call returns `confirmation_token`, second call
     includes it as a query parameter to execute the action.
3. Never auto-post. Always surface the confirmation requirement to the operator.
4. Tokens and credentials are never logged or returned in full.

## Required Scopes

- **Personal app (`/me`, `/share`)**:
  - `openid` — OpenID Connect authentication
  - `profile` — basic profile data
  - `email` — email address
  - `w_member_social` — create posts / shares (write)
- **Org app (organization reads)**:
  - `r_organization_social` / `rw_organization_admin` — read Company Pages.
    Requires LinkedIn's Community Management API access on the separate org
    app and re-authentication via `/auth/org/login` once approved.

## Configuration

All configuration is loaded from a single JSON file (`config/config.json`).
There is no environment-variable overlay — the file is the sole source of
truth. Operators can view and update configuration through the Settings
panel endpoints:

```
GET  /config          — view current config (secrets masked)
PUT  /config          — update config fields (partial updates supported)
GET  /config/schema   — JSON Schema for the config model
```

### Config fields

| Field | Required | Default | Description |
|---|---|---|---|
| `linkedin_client_id` | Yes | `""` | Personal LinkedIn app OAuth 2.0 client ID (secret) |
| `linkedin_client_secret` | Yes | `""` | Personal LinkedIn app client secret (secret) |
| `linkedin_redirect_uri` | Yes | `http://localhost:8000/auth/callback` | Personal-app OAuth redirect URI |
| `linkedin_allowed_redirect_uris` | No | `""` | Space- or comma-separated extra redirect URIs |
| `linkedin_scopes` | No | `openid profile email w_member_social` | Personal-app OAuth scopes |
| `linkedin_token_file` | No | `~/.config/linkedin-service/tokens.json` | Personal token persistence path |
| `linkedin_org_client_id` | No | `""` | Dedicated org-app client ID (secret) |
| `linkedin_org_client_secret` | No | `""` | Dedicated org-app client secret (secret) |
| `linkedin_org_redirect_uri` | No | `http://localhost:8000/auth/org/callback` | Org-app OAuth redirect URI |
| `linkedin_org_scopes` | No | `r_organization_social rw_organization_admin` | Org-app scopes |
| `linkedin_org_token_file` | No | `~/.config/linkedin-service/org-tokens.json` | Org token persistence path |
| `host` | No | `0.0.0.0` | Bind host |
| `port` | No | `8000` | Bind port |
| `require_operator_confirmation` | No | `true` | Require confirmation for writes |

Secret fields (`linkedin_client_id`, `linkedin_client_secret`,
`linkedin_org_client_id`, `linkedin_org_client_secret`) are masked in
`GET /config` responses and marked `writeOnly` in the JSON Schema.

When credentials are not yet configured, the service boots but `/auth/login`
(and `/auth/org/login` for the org app) return 503.