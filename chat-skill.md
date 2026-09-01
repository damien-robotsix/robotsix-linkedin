---
name: robotsix-linkedin
description: Drive the LinkedIn API service — read the authenticated profile and post operator-gated shares.
---

# Chat Skill — robotsix-linkedin

## Overview

LinkedIn API service for fleet agents. Provides OAuth 2.0 authentication,
profile reads, and operator-gated write actions (posting / sharing).

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

| Method | Path             | Description                                      | Auth required |
|--------|------------------|--------------------------------------------------|---------------|
| GET    | `/auth/login`    | Redirect operator to LinkedIn consent screen     | No            |
| GET    | `/auth/callback` | OAuth redirect handler — exchanges code for token | No            |

### Read

| Method | Path                    | Description                                            | Auth required |
|--------|-------------------------|--------------------------------------------------------|---------------|
| GET    | `/me`                   | Authenticated member's profile                         | Yes           |
| GET    | `/organizations`        | List Company Pages the member administers (id, name, vanity name, logo) | Yes |
| GET    | `/organizations/{id}`   | Fetch one Company Page's admin-visible details by organization id | Yes |

> **Organizations note:** `/organizations` and `/organizations/{id}` require
> LinkedIn **Community Management API access** plus an Organization scope
> (`r_organization_social` or `rw_organization_admin`) on the OAuth token. If
> the token's consent lacks the scope, they return a clear **403** explaining
> that the org scope must be added to `linkedin_scopes` and the operator must
> re-authenticate — they never fail silently.

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

- `openid` — OpenID Connect authentication
- `profile` — basic profile data
- `email` — email address
- `w_member_social` — create posts / shares (write)
- `r_organization_social` / `rw_organization_admin` — read Company Pages
  (organizations). Requires LinkedIn's Community Management API access and
  must be added to `linkedin_scopes` + re-authenticated once approved.

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
| `linkedin_client_id` | Yes | `""` | LinkedIn app OAuth 2.0 client ID (secret) |
| `linkedin_client_secret` | Yes | `""` | LinkedIn app OAuth 2.0 client secret (secret) |
| `linkedin_redirect_uri` | Yes | `http://localhost:8000/auth/callback` | OAuth redirect URI |
| `linkedin_allowed_redirect_uris` | No | `""` | Space- or comma-separated extra redirect URIs |
| `linkedin_scopes` | No | `openid profile email w_member_social` | OAuth scopes |
| `linkedin_token_file` | No | `~/.config/linkedin-service/tokens.json` | Token persistence path |
| `host` | No | `0.0.0.0` | Bind host |
| `port` | No | `8000` | Bind port |
| `require_operator_confirmation` | No | `true` | Require confirmation for writes |

Secret fields (`linkedin_client_id`, `linkedin_client_secret`) are masked in
`GET /config` responses and marked `writeOnly` in the JSON Schema.

When credentials are not yet configured, the service boots but `/auth/login`
returns 503.
