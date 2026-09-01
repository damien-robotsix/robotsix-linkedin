# robotsix-linkedin

LinkedIn API service for fleet agents — OAuth 2.0 authentication, profile reads, and operator-gated writes.

## Quick Start

```bash
# Install
pip install ".[dev]"

# Configure — edit config/config.json (the single source of truth)
# or use the Settings API:
#   GET  /config        — view current config (secrets masked)
#   PUT  /config        — update config fields
#   GET  /config/schema — JSON Schema for the config model

# Run (stubs auth when credentials are missing)
python -m linkedin_service

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

### Required Scopes — personal app (Sign In + posts)

| Scope                | Purpose                          |
|----------------------|----------------------------------|
| `openid`             | OpenID Connect authentication    |
| `profile`            | Basic profile data               |
| `email`              | Member email address             |
| `w_member_social`    | Create posts / shares (write)    |

### Dedicated org app (Company Page reads)

Reading organization / Company Page data requires LinkedIn's **Community
Management API**, which must live in a **separate LinkedIn app** with its own
credentials:

1. Create a second LinkedIn app and request access to **Community Management
   API** (may require LinkedIn review).
2. Under **Products**, add **Organization Social Content** /
   **Community Management** and request the org scopes.
3. Record the org app's **Client ID** / **Client Secret** and configure
   `linkedin_org_client_id` / `linkedin_org_client_secret`.
4. Add `http://localhost:8000/auth/org/callback` to the org app's allowed
   redirect URLs.
5. Complete `/auth/org/login` **once** so the org token is stored in its own
   token file (never overwrites the personal token).

Org scopes (`r_organization_social` / `rw_organization_admin`) are requested
by the org app's consent flow and are read-only for Company Pages. If the
org app is not configured, `/organizations` returns a clear 403 (never a
silent 500).

## Configuration

All configuration is loaded from a single JSON file (`config/config.json`).
There is **no environment-variable overlay** — the file is the sole source of
truth. The config file path can be overridden with `ROBOTSIX_CONFIG_FILE`
(default: `config/config.json`).

Operators can view and update configuration through the Settings panel API:

```
GET  /config        — view current config (secrets masked)
PUT  /config        — update config fields (partial updates supported)
GET  /config/schema — JSON Schema for the config model
```

### Config fields

| Field | Required | Default | Description |
|---|---|---|---|
| `linkedin_client_id` | Yes* | `""` | LinkedIn app client ID (secret) |
| `linkedin_client_secret` | Yes* | `""` | LinkedIn app client secret (secret) |
| `linkedin_redirect_uri` | Yes | `http://localhost:8000/auth/callback` | OAuth redirect URI |
| `linkedin_allowed_redirect_uris` | No | `""` | Space- or comma-separated extra redirect URIs |
| `linkedin_scopes` | No | `openid profile email w_member_social` | Space-separated scope list |
| `linkedin_token_file` | No | `~/.config/linkedin-service/tokens.json` | Token persistence path (outside the repo) |
| `linkedin_org_client_id` | No | `""` | Dedicated org-app client ID (secret) |
| `linkedin_org_client_secret` | No | `""` | Dedicated org-app client secret (secret) |
| `linkedin_org_redirect_uri` | No | `http://localhost:8000/auth/org/callback` | Org-app OAuth redirect URI |
| `linkedin_org_scopes` | No | `r_organization_social rw_organization_admin` | Org-app scope list |
| `linkedin_org_token_file` | No | `~/.config/linkedin-service/org-tokens.json` | Org token persistence path (outside the repo) |
| `host` | No | `0.0.0.0` | Bind host |
| `port` | No | `8000` | Bind port |
| `require_operator_confirmation` | No | `true` | Require confirmation for writes |

\* When credentials are not configured, the service boots but `/auth/login`
returns 503. `/health` still returns 200.

Secret fields (`linkedin_client_id`, `linkedin_client_secret`,
`linkedin_org_client_id`, `linkedin_org_client_secret`) are masked in
`GET /config` responses and marked `writeOnly` in the JSON Schema.

### Settings panel API

Operators can view and update configuration through the component's own API:

```bash
# View current config (secrets are masked)
curl http://localhost:8000/config

# Update credentials
curl -X PUT http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -d '{"linkedin_client_id": "your-id", "linkedin_client_secret": "your-secret"}'

# View the JSON Schema
curl http://localhost:8000/config/schema
```

`PUT /config` supports partial updates — only include the fields you want to
change. Omitted fields keep their current values.

### Config File Format

A minimal `config/config.json`:

```json
{
  "linkedin_client_id": "<YOUR_CLIENT_ID>",
  "linkedin_client_secret": "<YOUR_CLIENT_SECRET>",
  "linkedin_redirect_uri": "https://your-domain.example.com/auth/callback"
}
```

All other fields are optional and fall back to their defaults. The full
template is at [`config/config.json`](config/config.json) and the schema at
[`config/config.schema.json`](config/config.schema.json). Secret fields
(`linkedin_client_id`, `linkedin_client_secret`, `linkedin_org_client_id`,
`linkedin_org_client_secret`) use `"format": "password"` and `"writeOnly":
true` so the deploy plane knows which fields to source from a secrets
manager rather than a plain config store.

### Fleet Deployment

For fleet deployment, use `deploy/docker-compose.yml`:

```bash
docker compose -f deploy/docker-compose.yml up
```

This compose file:
- Declares the `robotsix.deploy.config-target: /app/config/config.json` label, which tells the deploy plane where to mount the config file.
- Sets `ROBOTSIX_CONFIG_FILE=/app/config/config.json` to direct the app to read the injected config.
- Includes the fleet-standard health check.

The deploy plane mounts `config/config.json` (built from
`config/config.schema.json`) at `/app/config/config.json` inside the
container, and the app loads it as the sole configuration source.

**Full deployment guide:** see [`DEPLOY.md`](DEPLOY.md) for step-by-step
operator instructions, config file format, field reference, and
troubleshooting.

## API Endpoints

### Config (Settings panel)

| Method | Path            | Description                            | Auth required |
|--------|-----------------|----------------------------------------|---------------|
| GET    | `/config`       | Current configuration (secrets masked) | No            |
| PUT    | `/config`       | Update configuration and persist       | No            |
| GET    | `/config/schema`| JSON Schema for the config model       | No            |

### `GET /chat-skill`

Returns the service's SKILL.md document (YAML frontmatter + overview, endpoints,
and safety rules) as `text/markdown`. Chat agents with chat access use this to
learn how to drive the service. Always returns 200.

### `GET /health`

Liveness probe. Always returns 200.

### `GET /auth/login`

Redirects the operator to LinkedIn's OAuth consent screen. Returns 503 if credentials are not configured.

### `GET /auth/callback?code=...&state=...`

Handles the OAuth redirect from LinkedIn. Exchanges the authorization code for tokens.

### `GET /auth/org/login`

Redirects the operator to the **dedicated org app's** consent screen
(Community Management API). Returns 503 if the org app credentials are not
configured. Its OAuth flow uses an independent token store so the personal
`/me` + `/share` token is never overwritten.

### `GET /auth/org/callback?code=...&state=...`

Handles the org app's OAuth redirect. Exchanges the authorization code for
the org token, persisted to `linkedin_org_token_file` (separate from the
personal token file).

### `GET /me`

Returns the authenticated member's profile (requires prior OAuth login).

### `GET /organizations`

Lists Company Pages the authenticated member administers (id, name, vanity
name, logo) via LinkedIn's `organizationAcls` API. Read-only — safe to call
without operator confirmation. Authenticates with the **org app's** token
(`/auth/org/login`) — never the personal token. Requires the org app to be
configured (`linkedin_org_client_id` / `linkedin_org_client_secret`) plus an
Organization scope (`r_organization_social` or `rw_organization_admin`) on
the org app's consent. If the org app is not configured, the scope is
missing, or LinkedIn rejects the call, it returns a clear 403 explaining
that Community Management API access + org scopes are needed — never a
silent 500.

### `GET /organizations/{id}`

Fetches a single Company Page's admin-visible details by LinkedIn
organization id via LinkedIn's `organizations` API. Read-only — safe to call
without operator confirmation. Same org-app + org-scope requirement as
`GET /organizations`.

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
- Credentials are stored in `config/config.json` (or set via `PUT /config`) and masked in API responses.
- There is no environment-variable overlay — the config file is the sole source of truth.

## Development

```bash
# Lint
ruff check src/ tests/

# Type check
mypy src/

# Test
pytest -v
```

For local development, edit `config/config.json` directly (the template
ships with empty placeholders), or use the Settings API:

```bash
curl -X PUT http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -d '{"linkedin_client_id": "your-id", "linkedin_client_secret": "your-secret"}'
```

## Docker

```bash
docker build -t robotsix-linkedin .
docker run -p 8000:8000 \
  -v "$(pwd)/config/config.json:/app/config/config.json" \
  robotsix-linkedin
```

Or with docker-compose:

```bash
docker compose up --build
```

## CI

GitHub Actions workflow (`.github/workflows/ci.yml`) runs lint, type check, tests, and Docker build on every push/PR to `main`.
