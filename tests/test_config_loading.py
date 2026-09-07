"""Integration tests for JSON config-file loading end-to-end.

These tests exercise the fleet-standard config-injection path: the deploy
plane mounts a ``config/config.json`` at the location named by the
``robotsix.deploy.config-target`` compose label, and the app must load its
settings from that file. They complement ``test_config.py`` (which covers
basic loading) by verifying that:

* every settings key can be sourced from the JSON config file,
* edge cases (missing file, malformed JSON, partial config) behave sanely,
* the LinkedIn OAuth credentials that come from the config file actually
  reach the OAuth client (authorize URL + token exchange), and
* the shipped ``config/config.json`` template is valid and loadable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from robotsix_config import InvalidConfigError, load_config

from linkedin_service import auth
from linkedin_service.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_CONFIG = REPO_ROOT / "config" / "config.json"


# ---------------------------------------------------------------------------
# Shipped template
# ---------------------------------------------------------------------------


def test_template_config_json_is_valid_and_loadable() -> None:
    """The committed ``config/config.json`` template parses and loads."""
    assert TEMPLATE_CONFIG.is_file()
    # Must be valid JSON.
    data = json.loads(TEMPLATE_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(data, dict)

    settings = load_config(Settings, TEMPLATE_CONFIG)

    # Template ships without real credentials (operator provisions later).
    assert settings.linkedin_client_id.get_secret_value() == ""
    assert settings.linkedin_client_secret.get_secret_value() == ""
    assert settings.auth_configured is False
    assert settings.linkedin_org_client_id.get_secret_value() == ""
    assert settings.linkedin_org_client_secret.get_secret_value() == ""
    assert settings.org_auth_configured is False
    assert settings.port == 8000


# ---------------------------------------------------------------------------
# Every key sourced from the config file
# ---------------------------------------------------------------------------


def test_every_setting_key_loads_from_config_file(tmp_path: Path) -> None:
    """Each config key has a scenario proving it is read from the file."""
    payload: dict[str, Any] = {
        "linkedin_client_id": "cid-from-file",
        "linkedin_client_secret": "csecret-from-file",
        "linkedin_redirect_uri": "https://app.example.com/auth/callback",
        "linkedin_allowed_redirect_uris": "https://alt.example.com/cb",
        "linkedin_scopes": "openid profile",
        "linkedin_token_file": "/var/lib/linkedin/tokens.json",
        "linkedin_org_client_id": "org-cid-from-file",
        "linkedin_org_client_secret": "org-csecret-from-file",
        "linkedin_org_redirect_uri": "https://app.example.com/auth/org/callback",
        "linkedin_org_scopes": "r_organization_social",
        "linkedin_org_token_file": "/var/lib/linkedin/org-tokens.json",
        "host": "127.0.0.1",
        "port": 9443,
        "require_operator_confirmation": False,
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(payload), encoding="utf-8")

    settings = load_config(Settings, cfg)

    assert settings.linkedin_client_id.get_secret_value() == "cid-from-file"
    assert settings.linkedin_client_secret.get_secret_value() == "csecret-from-file"
    assert settings.linkedin_redirect_uri == "https://app.example.com/auth/callback"
    assert settings.linkedin_allowed_redirect_uris == "https://alt.example.com/cb"
    assert settings.linkedin_scopes == "openid profile"
    assert settings.linkedin_token_file == "/var/lib/linkedin/tokens.json"
    assert settings.linkedin_org_client_id.get_secret_value() == "org-cid-from-file"
    assert settings.linkedin_org_client_secret.get_secret_value() == "org-csecret-from-file"
    assert settings.linkedin_org_redirect_uri == "https://app.example.com/auth/org/callback"
    assert settings.linkedin_org_scopes == "r_organization_social"
    assert settings.linkedin_org_token_file == "/var/lib/linkedin/org-tokens.json"
    assert settings.host == "127.0.0.1"
    assert settings.port == 9443
    assert settings.require_operator_confirmation is False

    # Derived helpers must reflect the file-sourced values too.
    assert settings.linkedin_scopes_list == ["openid", "profile"]
    assert settings.allowed_redirect_uris_list == [
        "https://app.example.com/auth/callback",
        "https://alt.example.com/cb",
    ]
    assert settings.auth_configured is True
    assert settings.linkedin_org_scopes_list == ["r_organization_social"]
    assert settings.org_allowed_redirect_uris_list == [
        "https://app.example.com/auth/org/callback",
        "https://alt.example.com/cb",
    ]
    assert settings.org_auth_configured is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_missing_config_file_falls_back_to_defaults(tmp_path: Path) -> None:
    """An absent config file is not fatal; field defaults apply."""
    settings = load_config(Settings, tmp_path / "nope.json")

    assert settings.port == 8000
    assert settings.host == "0.0.0.0"
    assert settings.linkedin_scopes == "openid profile email w_member_social"
    assert settings.linkedin_org_scopes == "r_organization_social rw_organization_admin"
    assert settings.auth_configured is False
    assert settings.org_auth_configured is False


def test_malformed_json_config_raises(tmp_path: Path) -> None:
    """A syntactically broken config file surfaces a decode error."""
    cfg = tmp_path / "config.json"
    cfg.write_text("{ this is not valid json", encoding="utf-8")

    with pytest.raises(InvalidConfigError):
        load_config(Settings, cfg)


def test_partial_config_keeps_defaults_for_missing_keys(
    tmp_path: Path,
) -> None:
    """Keys absent from the config file retain their field defaults."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"linkedin_client_id": "only-id"}), encoding="utf-8")

    settings = load_config(Settings, cfg)

    assert settings.linkedin_client_id.get_secret_value() == "only-id"
    # Everything else stays at its default.
    assert settings.linkedin_client_secret.get_secret_value() == ""
    assert settings.port == 8000
    assert settings.require_operator_confirmation is True


def test_wrong_type_in_config_fails_validation(tmp_path: Path) -> None:
    """A non-coercible value for a typed field raises a validation error."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"port": "not-a-number"}), encoding="utf-8")

    with pytest.raises(InvalidConfigError):
        load_config(Settings, cfg)


# ---------------------------------------------------------------------------
# Config credentials reach the OAuth client
# ---------------------------------------------------------------------------


def _apply_settings(monkeypatch: pytest.MonkeyPatch, source: Settings) -> None:
    """Copy file-loaded settings onto the module-level OAuth singleton.

    ``auth.settings`` and ``app.settings`` are the same object, so patching
    its attributes mirrors a process that booted with this config file.
    """
    for field in (
        "linkedin_client_id",
        "linkedin_client_secret",
        "linkedin_redirect_uri",
        "linkedin_allowed_redirect_uris",
        "linkedin_scopes",
        "linkedin_org_client_id",
        "linkedin_org_client_secret",
        "linkedin_org_redirect_uri",
        "linkedin_org_scopes",
    ):
        monkeypatch.setattr(auth.settings, field, getattr(source, field))


def test_config_credentials_build_authorize_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OAuth credentials from the config file drive the consent URL."""
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "linkedin_client_id": "cid-xyz",
                "linkedin_client_secret": "csecret-xyz",
                "linkedin_redirect_uri": "https://app.example.com/auth/callback",
                "linkedin_scopes": "openid w_member_social",
            }
        ),
        encoding="utf-8",
    )
    source = load_config(Settings, cfg)
    _apply_settings(monkeypatch, source)

    url = auth.build_authorize_url()

    assert "client_id=cid-xyz" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fauth%2Fcallback" in url
    assert "openid" in url and "w_member_social" in url


def test_config_credentials_build_org_authorize_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Org-app OAuth credentials from the config file drive the org consent URL."""
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "linkedin_org_client_id": "org-cid-xyz",
                "linkedin_org_client_secret": "org-csecret-xyz",
                "linkedin_org_redirect_uri": "https://app.example.com/auth/org/callback",
                "linkedin_org_scopes": "r_organization_social rw_organization_admin",
            }
        ),
        encoding="utf-8",
    )
    source = load_config(Settings, cfg)
    _apply_settings(monkeypatch, source)

    url = auth.build_org_authorize_url()

    assert "client_id=org-cid-xyz" in url
    assert (
        "redirect_uri=https%3A%2F%2Fapp.example.com%2Fauth%2Forg%2Fcallback" in url
    )
    assert "r_organization_social" in url and "rw_organization_admin" in url


class _FakeResponse:
    """Minimal stand-in for :class:`httpx.Response`."""

    def __init__(self, json_data: dict[str, Any]) -> None:
        self._json = json_data
        self.status_code = 200
        self.text = ""

    @property
    def is_error(self) -> bool:
        return False

    def json(self) -> dict[str, Any]:
        return self._json

    def raise_for_status(self) -> None:
        """No-op success response for RetryClient."""
        return None


class _FakeClient:
    """Async context-manager stand-in for ``httpx.AsyncClient``.

    ``RetryClient`` calls ``request(method, url, ...)``, so requests are
    recorded there (kwargs only, matching the prior ``post`` shape).
    """

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return self._response


@pytest.mark.asyncio
async def test_config_credentials_passed_to_token_exchange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The client id/secret from the config file are sent to LinkedIn."""
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "linkedin_client_id": "cid-exchange",
                "linkedin_client_secret": "csecret-exchange",
            }
        ),
        encoding="utf-8",
    )
    source = load_config(Settings, cfg)
    _apply_settings(monkeypatch, source)

    fake = _FakeClient(_FakeResponse({"access_token": "tok", "expires_in": 3600}))
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *a, **k: fake)
    auth.tokens.state = "state-xyz"

    await auth.exchange_code("the-code", "state-xyz")

    assert fake.calls, "token endpoint was not called"
    sent = fake.calls[0]["data"]
    assert sent["client_id"] == "cid-exchange"
    assert sent["client_secret"] == "csecret-exchange"


# ---------------------------------------------------------------------------
# End-to-end: no regression to the OAuth login flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_login_redirects_with_config_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: Any,
) -> None:
    """With credentials from the config file, /auth/login redirects to LinkedIn."""
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "linkedin_client_id": "cid-login",
                "linkedin_client_secret": "csecret-login",
            }
        ),
        encoding="utf-8",
    )
    source = load_config(Settings, cfg)
    _apply_settings(monkeypatch, source)

    resp = await client.get("/auth/login", follow_redirects=False)

    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    assert location.startswith(auth.AUTHORIZE_URL)
    assert "client_id=cid-login" in location
