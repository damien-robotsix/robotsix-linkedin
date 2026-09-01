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

The service reads its settings from a single JSON file (`config/config.json`).
There is no environment-variable overlay — the file is the sole source of
truth. The deploy plane injects this file into the container at the path
declared by the `robotsix.deploy.config-target` label
(`/app/config/config.json`).

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
  "linkedin_org_client_id": "",
  "linkedin_org_client_secret": "",
  "linkedin_org_redirect_uri": "http://localhost:8000/auth/org/callback",
  "linkedin_org_scopes": "r_organization_social rw_organization_admin",
  "linkedin_org_token_file": "~/.config/linkedin-service/org-tokens.json",
  "host": "0.0.0.0",
  "port": 8000,
  "require_operator_confirmation": true
}
```

### Field reference

| Field | Required | Description |
|---|---|---|
| `linkedin_client_id` | Yes | OAuth 2.0 client ID from the LinkedIn Developer Portal. Secret — masked in API responses, `writeOnly` in the schema. |
| `linkedin_client_secret` | Yes | OAuth 2.0 client secret. Secret — masked in API responses, `writeOnly` in the schema. |
| `linkedin_redirect_uri` | Yes | Must exactly match the redirect URL registered on the LinkedIn app. |
| `linkedin_allowed_redirect_uris` | No | Space- or comma-separated extra redirect URIs. Leave empty if only one redirect URI is needed. |
| `linkedin_scopes` | No | OAuth scopes requested on the consent screen. Default covers sign-in and posting. |
| `linkedin_token_file` | No | Path for persisted OAuth tokens. Set to `""` to disable on-disk persistence. |
| `linkedin_org_client_id` | No | Dedicated org-app (Community Management API) client ID. Secret — masked in API responses, `writeOnly` in the schema. Empty means `/organizations` returns a clear 403. |
| `linkedin_org_client_secret` | No | Dedicated org-app client secret. Secret — masked in API responses, `writeOnly` in the schema. |
| `linkedin_org_redirect_uri` | No | Must match a redirect URL registered on the org LinkedIn app. Default `http://localhost:8000/auth/org/callback`. |
| `linkedin_org_scopes` | No | Org-app scopes. Default `r_organization_social rw_organization_admin`. |
| `linkedin_org_token_file` | No | Path for persisted org-app tokens. Separate from `linkedin_token_file` so the org flow never overwrites the personal token. |
| `host` / `port` | No | Service bind address. Default `0.0.0.0:8000`. |
| `require_operator_confirmation` | No | When `true`, write endpoints require an explicit confirmation token before calling LinkedIn. |

> **Two LinkedIn apps:** `/me` and `/share` use the personal app
> (`linkedin_client_id` / `linkedin_client_secret`). Organization / Company
> Page reads (`/organizations`, `/organizations/{id}`) use a **separate org
> app** (`linkedin_org_client_id` / `linkedin_org_client_secret`) that must
> have Community Management API access approved by LinkedIn, plus its own
> consent flow (`/auth/org/login`, `/auth/org/callback`) so the two token
> stores coexist.

The full JSON Schema is at [`config/config.schema.json`](config/config.schema.json).
Secret fields use `"format": "password"` and `"writeOnly": true` annotations
so the deploy plane knows which fields to source from a secrets manager rather
than a plain config store.

### Settings panel API

Operators can also view and update configuration through the component's own
API, without needing access to the deploy plane:

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

## 2. Deploy with docker-compose

The fleet compose file is at [`deploy/docker-compose.yml`](deploy/docker-compose.yml).

```bash
docker compose -f deploy/docker-compose.yml up -d
```

This compose file:

- Pulls `ghcr.io/damien-robotsix/robotsix-linkedin:main`.
- Declares the `robotsix.deploy.config-target: /app/config/config.json`
  label, which tells the deploy plane where to mount the config file.
- Sets `ROBOTSIX_CONFIG_FILE=/app/config/config.json` so the app reads the
  injected file.
- Includes a health check that polls `/health`.

### How config injection works

1. The deploy plane reads the `robotsix.deploy.config-target` label from the
   compose file.
2. It builds `config/config.json` from the schema (`config/config.schema.json`),
   filling secret fields from the fleet's secrets manager.
3. It mounts the resulting file at `/app/config/config.json` inside the
   container.
4. On startup, the app loads this file as its sole configuration source.

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
correctly, or set credentials via `PUT /config`.

## 4. Configure the LinkedIn redirect URI

In the [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps),
set the **Authorized redirect URLs** to match `linkedin_redirect_uri` in your
config (e.g. `https://your-domain.example.com/auth/callback`). The OAuth flow
rejects any redirect URI not on the allowlist.

## Local development

For local development, edit `config/config.json` directly:

```bash
# Edit config/config.json with your LinkedIn app credentials
# (the template ships with empty placeholders)

pip install ".[dev]"
python -m linkedin_service
```

Or with the root `docker-compose.yml` (builds from source, mounts
`config/` from the host):

```bash
docker compose up --build
```

You can also use the Settings API to set credentials without editing files:

```bash
curl -X PUT http://localhost:8000/config \
  -H "Content-Type: application/json" \
  -d '{"linkedin_client_id": "your-id", "linkedin_client_secret": "your-secret"}'
```

## Compose conventions

Every service in `deploy/docker-compose.yml` **must** carry:

1. **Contract-version header** — the file starts with
   `# central-deploy-contract-version: 1`. The deploy API rejects compose
   files missing this header.
2. **`robotsix.deploy.config-target` label** — declares the in-container
   path where the deploy plane injects the config file. A matching named
   volume mount must cover that path, and the volume must be declared in
   the top-level `volumes:` block.
3. **Standard fleet deploy labels:**

   | Label | Purpose |
   |---|---|
   | `robotsix.deploy.label.service` | Service name used by the fleet router |
   | `robotsix.deploy.label.description` | Human-readable one-liner |
   | `robotsix.deploy.label.health.endpoint` | HTTP path the deploy plane polls for health |
   | `robotsix.deploy.label.port` | Container port the service listens on |
   | `robotsix.deploy.label.chat-access` | Access level for fleet chat agents (`read`, `write`, or `none`) |
   | `robotsix.deploy.chat-access` | Standard chat-access opt-in label — set to `"true"` to register the service in the chat roster and require it to serve `GET /chat-skill` |

These requirements match the robotsix fleet contract. Omitting any of them
causes registration failures when the deploy plane validates the compose file.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/auth/login` returns 503 | Credentials not loaded | Check `config/config.json` was injected; verify `linkedin_client_id` and `linkedin_client_secret` are non-empty. Or set via `PUT /config`. |
| `/auth/org/login` returns 503 | Org app not configured | Set `linkedin_org_client_id` and `linkedin_org_client_secret`, or `PUT /config`. |
| `/organizations` returns 403 | Org app unconfigured, org scope missing, or LinkedIn rejected the call | Confirm Community Management API access is approved, `linkedin_org_client_id` / `linkedin_org_client_secret` are set, `linkedin_org_scopes` includes an org scope, and `/auth/org/login` was completed once. |
| OAuth callback fails with redirect mismatch | `linkedin_redirect_uri` doesn't match LinkedIn app config | Ensure the value in config exactly matches the LinkedIn Developer Portal setting |
| Container fails to start | Config file not found at `/app/config/config.json` | Verify the `robotsix.deploy.config-target` label and volume mount are correct |
