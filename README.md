# robotsix-linkedin

LinkedIn API service for fleet agents — OAuth 2.0 authentication, profile reads, and operator-gated writes.

## Quick Start

```bash
# Install
pip install ".[dev]"

# Configure — copy the template and fill in real values (never commit .env)
cp .env.example .env

# Run (stubs auth when credentials are missing)
LINKEDIN_CLIENT_ID=... LINKEDIN_CLIENT_SECRET=... python -m linkedin_service

# Or with Docker
docker compose up --build
```

The service starts on `http://localhost:8000`. Visit `/health` to confirm.

## LinkedIn App Setup

1. Go to [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps) and create an app.
2. Under **Auth** tab, note your **Client ID** and **Client Secret**.
3. Add a redirect URL (e.g. `http://localhost:8000/auth/callback`).
4. Under **Products**, request access to:
   - **Sign In with LinkedIn using OpenID Connect** — required for `openid`, `profile`, `email` scopes.
   - **Share on LinkedIn** — required for `w_member_social` scope (write / share).
5. Wait for product approval (may require LinkedIn review).

### Required Scopes

| Scope                | Purpose                          |
|----------------------|----------------------------------|
| `openid`             | OpenID Connect authentication    |
| `profile`            | Basic profile data               |
| `email`              | Member email address             |
| `w_member_social`    | Create posts / shares (write)    |

## Configuration

All configuration is via environment variables (prefix `LINKEDIN_`). See
[`.env.example`](.env.example) for a copy-ready template with placeholder
values only — never commit a populated `.env` (it is git-ignored).

| Variable                                      | Required | Default                               | Description                                 |
|-----------------------------------------------|----------|---------------------------------------|---------------------------------------------|
| `LINKEDIN_CLIENT_ID`                          | Yes*     | `""`                                  | LinkedIn app client ID                      |
| `LINKEDIN_CLIENT_SECRET`                      | Yes*     | `""`                                  | LinkedIn app client secret                  |
| `LINKEDIN_REDIRECT_URI`                       | No       | `http://localhost:8000/auth/callback` | OAuth redirect URI                          |
| `LINKEDIN_ALLOWED_REDIRECT_URIS`              | No       | `""`                                  | Extra allowed redirect URIs (space/comma)   |
| `LINKEDIN_SCOPES`                             | No       | `openid profile email w_member_social`| Space-separated scope list                  |
| `LINKEDIN_HOST`                               | No       | `0.0.0.0`                             | Bind host                                   |
| `LINKEDIN_PORT`                               | No       | `8000`                                | Bind port                                   |
| `LINKEDIN_REQUIRE_OPERATOR_CONFIRMATION`      | No       | `True`                                | Require confirmation for writes             |

\* When not set, the service boots but `/auth/login` returns 503. `/health` still returns 200.

The OAuth flow validates the redirect URI against an allowlist
(`LINKEDIN_REDIRECT_URI` plus any entries in `LINKEDIN_ALLOWED_REDIRECT_URIS`)
before contacting LinkedIn, rejecting any value not on the list.

## API Endpoints

### `GET /health`

Liveness probe. Always returns 200.

### `GET /auth/login`

Redirects the operator to LinkedIn's OAuth consent screen. Returns 503 if credentials are not configured.

### `GET /auth/callback?code=...&state=...`

Handles the OAuth redirect from LinkedIn. Exchanges the authorization code for tokens.

### `GET /me`

Returns the authenticated member's profile (requires prior OAuth login).

### `POST /share?text=...&visibility=PUBLIC`

Creates a text post on the authenticated member's feed. **State-mutating** —
requires operator confirmation:

1. First call returns a `confirmation_token`.
2. Re-submit with `&confirmation_token=...` to execute.

On success the response includes the created post URN, e.g.
`{"status": "posted", "result": {"id": "urn:li:share:...", "urn": "urn:li:share:...", ...}}`.

## Safety

- All **read** endpoints are safe to call without operator approval.
- All **write** endpoints are **state-mutating** and gated behind operator confirmation.
- Tokens and credentials are never committed to the repository.
- Credentials are loaded from environment variables / config volume.

## Development

```bash
# Lint
ruff check src/ tests/

# Type check
mypy src/

# Test
pytest -v
```

## Docker

```bash
docker build -t robotsix-linkedin .
docker run -p 8000:8000 \
  -e LINKEDIN_CLIENT_ID=... \
  -e LINKEDIN_CLIENT_SECRET=... \
  robotsix-linkedin
```

Or with docker-compose:

```bash
docker compose up --build
```

## CI

GitHub Actions workflow (`.github/workflows/ci.yml`) runs lint, type check, tests, and Docker build on every push/PR to `main`.
