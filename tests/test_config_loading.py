"""Integration tests for JSON config-file loading end-to-end.

These tests exercise the fleet-standard config-injection path: the deploy
plane mounts a ``config/config.json`` at the location named by the
``robotsix.deploy.config-target`` compose label, and the app must load its
settings from that file. They complement ``test_config.py`` (which covers
source-priority ordering) by verifying that:

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
from pydantic_settings import SettingsConfigDict

from linkedin_service import auth
from linkedin_service.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_CONFIG = REPO_ROOT / "config" / "config.json"

# The full set of LINKEDIN_* env vars that could otherwise shadow the config
# file. Cleared per-test so the JSON file is unambiguously the source read.
_ENV_VARS = (
    "LINKEDIN_LINKEDIN_CLIENT_ID",
    "LINKEDIN_LINKEDIN_CLIENT_SECRET",
    "LINKEDIN_LINKEDIN_REDIRECT_URI",
    "LINKEDIN_LINKEDIN_ALLOWED_REDIRECT_URIS",
    "LINKEDIN_LINKEDIN_SCOPES",
    "LINKEDIN_LINKEDIN_TOKEN_FILE",
    "LINKEDIN_HOST",
    "LINKEDIN_PORT",
    "LINKEDIN_REQUIRE_OPERATOR_CONFIRMATION",
)


def _settings_class_for(json_file: Path) -> type[Settings]:
    """Build a ``Settings`` subclass whose config file is ``json_file``."""

    class _Settings(Settings):
        model_config = SettingsConfigDict(
            env_prefix="LINKEDIN_",
            env_file=".env",
            extra="ignore",
            json_file=str(json_file),
            json_file_encoding="utf-8",
        )

    return _Settings


@pytest.fixture
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove LINKEDIN_* overrides so the JSON file is the only source."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Shipped template
# ---------------------------------------------------------------------------

def test_template_config_json_is_valid_and_loadable(_clean_env: None) -> None:
    """The committed ``config/config.json`` template parses and loads."""
    assert TEMPLATE_CONFIG.is_file()
    # Must be valid JSON.
    data = json.loads(TEMPLATE_CONFIG.read_text(encoding="utf-8"))
    assert isinstance(data, dict)

    settings = _settings_class_for(TEMPLATE_CONFIG)()

    # Template ships without real credentials (operator provisions later).
    assert settings.linkedin_client_id == ""
    assert settings.linkedin_client_secret == ""
    assert settings.auth_configured is False
    assert settings.port == 8000


# ---------------------------------------------------------------------------
# Every key sourced from the config file
# ---------------------------------------------------------------------------

def test_every_setting_key_loads_from_config_file(
    tmp_path: Path, _clean_env: None
) -> None:
    """Each config key has a scenario proving it is read from the file."""
    payload: dict[str, Any] = {
        "linkedin_client_id": "cid-from-file",
        "linkedin_client_secret": "csecret-from-file",
        "linkedin_redirect_uri": "https://app.example.com/auth/callback",
        "linkedin_allowed_redirect_uris": "https://alt.example.com/cb",
        "linkedin_scopes": "openid profile",
        "linkedin_token_file": "/var/lib/linkedin/tokens.json",
        "host": "127.0.0.1",
        "port": 9443,
        "require_operator_confirmation": False,
    }
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(payload), encoding="utf-8")

    settings = _settings_class_for(cfg)()

    assert settings.linkedin_client_id == "cid-from-file"
    assert settings.linkedin_client_secret == "csecret-from-file"
    assert settings.linkedin_redirect_uri == "https://app.example.com/auth/callback"
    assert settings.linkedin_allowed_redirect_uris == "https://alt.example.com/cb"
    assert settings.linkedin_scopes == "openid profile"
    assert settings.linkedin_token_file == "/var/lib/linkedin/tokens.json"
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


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_missing_config_file_falls_back_to_defaults(
    tmp_path: Path, _clean_env: None
) -> None:
    """An absent config file is not fatal; field defaults apply."""
    settings = _settings_class_for(tmp_path / "nope.json")()

    assert settings.port == 8000
    assert settings.host == "0.0.0.0"
    assert settings.linkedin_scopes == "openid profile email w_member_social"
    assert settings.auth_configured is False


def test_malformed_json_config_raises(
    tmp_path: Path, _clean_env: None
) -> None:
    """A syntactically broken config file surfaces a decode error."""
    cfg = tmp_path / "config.json"
    cfg.write_text("{ this is not valid json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        _settings_class_for(cfg)()


def test_partial_config_keeps_defaults_for_missing_keys(
    tmp_path: Path, _clean_env: None
) -> None:
    """Keys absent from the config file retain their field defaults."""
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"linkedin_client_id": "only-id"}), encoding="utf-8"
    )

    settings = _settings_class_for(cfg)()

    assert settings.linkedin_client_id == "only-id"
    # Everything else stays at its default.
    assert settings.linkedin_client_secret == ""
    assert settings.port == 8000
    assert settings.require_operator_confirmation is True


def test_wrong_type_in_config_fails_validation(
    tmp_path: Path, _clean_env: None
) -> None:
    """A non-coercible value for a typed field raises a validation error."""
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"port": "not-a-number"}), encoding="utf-8"
    )

    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        _settings_class_for(cfg)()


# ---------------------------------------------------------------------------
# Config credentials reach the OAuth client
# ---------------------------------------------------------------------------

def _apply_settings(
    monkeypatch: pytest.MonkeyPatch, source: Settings
) -> None:
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
    ):
        monkeypatch.setattr(auth.settings, field, getattr(source, field))


def test_config_credentials_build_authorize_url(
    tmp_path: Path, _clean_env: None, monkeypatch: pytest.MonkeyPatch
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
    source = _settings_class_for(cfg)()
    _apply_settings(monkeypatch, source)

    url = auth.build_authorize_url()

    assert "client_id=cid-xyz" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fauth%2Fcallback" in url
    assert "openid" in url and "w_member_social" in url


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


class _FakeClient:
    """Async context-manager stand-in for ``httpx.AsyncClient``."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def post(self, *_args: Any, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return self._response


@pytest.mark.asyncio
async def test_config_credentials_passed_to_token_exchange(
    tmp_path: Path, _clean_env: None, monkeypatch: pytest.MonkeyPatch
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
    source = _settings_class_for(cfg)()
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
    _clean_env: None,
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
    source = _settings_class_for(cfg)()
    _apply_settings(monkeypatch, source)

    resp = await client.get("/auth/login", follow_redirects=False)

    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    assert location.startswith(auth.AUTHORIZE_URL)
    assert "client_id=cid-login" in location
