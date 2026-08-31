# Deploying robotsix-linkedin

Step-by-step guide for fleet operators deploying `robotsix-linkedin` into a
robotsix fleet environment.

## Prerequisites

- A LinkedIn Developer app with OAuth 2.0 credentials
  ([LinkedIn Developer Portal](https://www.linkedin.com/developers/apps)).
- The app must have **Sign In with LinkedIn using OpenID Connect** and
  (optionally) **Share on LinkedIn** products approved.
- A container runtime with access to `ghcr.io/damien-robotsix/robotsix-linkedin`.

## 1. Prepare the config file

The service reads its settings from `config/config.json`. The deploy plane
injects this file into the container at the path declared by the
`robotsix.deploy.config-target` label (`/app/config/config.json`).

Create a `config/config.json` on your deploy host (or in your config store)
using the template below. **Replace the placeholder values with real
credentials — never commit real secrets to the repository.**

```json
{
  "linkedin_client_id": "<YOUR_LINKEDIN_CLIENT_ID>",
  "linkedin_client_secret": "<YOUR_LINKEDIN_CLIENT_SECRET>",
  "linkedin_redirect_uri": "https://your-domain.example.com/auth/callback",
  "linkedin_allowed_redirect_uris": "",
  "linkedin_scopes": "openid profile email w_member_social",
  "linkedin_token_file": "~/.config/linkedin-service/tokens.json",
  "host": "0.0.0.0",
  "port": 8000,
  "require_operator_confirmation": true
}
```

### Field reference

| Field | Required | Description |
|---|---|---|
| `linkedin_client_id` | Yes | OAuth 2.0 client ID from the LinkedIn Developer Portal. Marked `secret` in the schema — the deploy plane reads it from a secure store. |
| `linkedin_client_secret` | Yes | OAuth 2.0 client secret. Marked `secret` and `writeOnly` — never logged or echoed. |
| `linkedin_redirect_uri` | Yes | Must exactly match the redirect URL registered on the LinkedIn app. |
| `linkedin_allowed_redirect_uris` | No | Space- or comma-separated extra redirect URIs. Leave empty if only one redirect URI is needed. |
| `linkedin_scopes` | No | OAuth scopes requested on the consent screen. Default covers sign-in and posting. |
| `linkedin_token_file` | No | Path for persisted OAuth tokens. Set to `""` to disable on-disk persistence. |
| `host` / `port` | No | Service bind address. Default `0.0.0.0:8000`. |
| `require_operator_confirmation` | No | When `true`, write endpoints require an explicit confirmation token before calling LinkedIn. |

The full JSON Schema is at [`config/config.schema.json`](config/config.schema.json).
The schema uses `"secret": true` and `"writeOnly": true` annotations so the
deploy plane knows which fields to source from a secrets manager rather than
a plain config store.

## 2. Deploy with docker-compose

The fleet compose file is at [`deploy/docker-compose.yml`](deploy/docker-compose.yml).

```bash
docker compose -f deploy/docker-compose.yml up -d
```

This compose file:

- Pulls `ghcr.io/damien-robotsix/robotsix-linkedin:main`.
- Declares the `robotsix.deploy.config-target: /app/config/config.json`
  label, which tells the deploy plane where to mount the config file.
- Sets `LINKEDIN_CONFIG_FILE=/app/config/config.json` so the app reads the
  injected file.
- Includes a health check that polls `/health`.

### How config injection works

1. The deploy plane reads the `robotsix.deploy.config-target` label from the
   compose file.
2. It builds `config/config.json` from the schema (`config/config.schema.json`),
   filling secret fields from the fleet's secrets manager.
3. It mounts the resulting file at `/app/config/config.json` inside the
   container.
4. On startup, the app loads this file as its primary configuration source.

## 3. Verify the deployment

```bash
# Check the container is healthy
docker compose -f deploy/docker-compose.yml ps

# Confirm the service responds
curl http://localhost:8000/health
# Expected: {"status": "ok"}

# Confirm OAuth is configured (credentials loaded)
curl http://localhost:8000/auth/login -o /dev/null -w "%{http_code}"
# Expected: 302 (redirect to LinkedIn) — NOT 503
```

A `503` from `/auth/login` means `linkedin_client_id` or
`linkedin_client_secret` are empty. Verify the config file was injected
correctly.

## 4. Configure the LinkedIn redirect URI

In the [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps),
set the **Authorized redirect URLs** to match `linkedin_redirect_uri` in your
config (e.g. `https://your-domain.example.com/auth/callback`). The OAuth flow
rejects any redirect URI not on the allowlist.

## Migration from env-var-only configuration

Previous versions of `robotsix-linkedin` read settings exclusively from
`LINKEDIN_*` environment variables. The current version uses
`config/config.json` as the **source of truth** in deployed environments.

**What changed:**

- `config/config.json` is now the primary configuration source in deployed
  containers. The deploy plane injects it automatically.
- `LINKEDIN_*` environment variables are still supported as **overrides** —
  they take precedence over the config file. This is useful for local
  development, testing, or emergency overrides.
- The `.env` file is loaded for local development only (between env vars and
  the config file in precedence).
- No functionality was removed. Existing `LINKEDIN_*` env vars continue to
  work. The change is additive — the config file is a new, lower-priority
  source that the deploy plane manages.

**Precedence** (highest to lowest):

1. Explicit init arguments (programmatic use)
2. `LINKEDIN_*` environment variables
3. `.env` file (local development)
4. `config/config.json` (deployed environments — injected by the deploy plane)

If you previously set `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET` as
environment variables in your compose file or orchestrator, those still work.
However, the recommended approach for fleet deployment is to let the deploy
plane inject `config/config.json` with secrets from the fleet secrets manager.

## Local development

For local development, continue using environment variables or a `.env` file:

```bash
cp .env.example .env
# Edit .env with your LinkedIn app credentials

pip install ".[dev]"
python -m linkedin_service
```

Or with the root `docker-compose.yml` (builds from source, uses env vars):

```bash
docker compose up --build
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/auth/login` returns 503 | Credentials not loaded | Check `config/config.json` was injected; verify `linkedin_client_id` and `linkedin_client_secret` are non-empty |
| OAuth callback fails with redirect mismatch | `linkedin_redirect_uri` doesn't match LinkedIn app config | Ensure the value in config exactly matches the LinkedIn Developer Portal setting |
| Container fails to start | Config file not found at `/app/config/config.json` | Verify the `robotsix.deploy.config-target` label and that the deploy plane mounted the file |
| `ModuleNotFoundError` on startup | Missing dependency | Run `pip install ".[dev]"` or rebuild the Docker image |
