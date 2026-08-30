# Chat Skill — robotsix-linkedin

## Overview

LinkedIn API service for fleet agents. Provides OAuth 2.0 authentication,
profile reads, and operator-gated write actions (posting / sharing).

## Endpoints

### Infra

| Method | Path      | Description          | Auth required |
|--------|-----------|----------------------|---------------|
| GET    | `/health` | Liveness probe       | No            |

### Auth (OAuth 2.0 — 3-legged)

| Method | Path             | Description                                      | Auth required |
|--------|------------------|--------------------------------------------------|---------------|
| GET    | `/auth/login`    | Redirect operator to LinkedIn consent screen     | No            |
| GET    | `/auth/callback` | OAuth redirect handler — exchanges code for token | No            |

### Read

| Method | Path  | Description                          | Auth required |
|--------|-------|--------------------------------------|---------------|
| GET    | `/me` | Authenticated member's profile       | Yes           |

### Write (state-mutating — operator-gated)

| Method | Path     | Description                    | Auth required | Confirmation |
|--------|----------|--------------------------------|---------------|--------------|
| POST   | `/share` | Create a share / post on LinkedIn | Yes           | **Yes**      |

## Safety Rules

1. **Read endpoints** (`/me`) are safe to call without operator approval.
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

## Configuration

All config is via environment variables (prefix `LINKEDIN_`):

| Variable                    | Required | Default                              | Description                     |
|-----------------------------|----------|--------------------------------------|---------------------------------|
| `LINKEDIN_CLIENT_ID`        | Yes*     | `""`                                 | LinkedIn app client ID          |
| `LINKEDIN_CLIENT_SECRET`    | Yes*     | `""`                                 | LinkedIn app client secret      |
| `LINKEDIN_REDIRECT_URI`     | No       | `http://localhost:8000/auth/callback`| OAuth redirect URI              |
| `LINKEDIN_SCOPES`           | No       | `openid profile email w_member_social`| Space-separated scope list     |
| `LINKEDIN_HOST`             | No       | `0.0.0.0`                            | Bind host                       |
| `LINKEDIN_PORT`             | No       | `8000`                               | Bind port                       |
| `LINKEDIN_REQUIRE_OPERATOR_CONFIRMATION` | No | `True`                        | Require confirmation for writes |

\* When not set, the service boots but `/auth/login` returns 503.
