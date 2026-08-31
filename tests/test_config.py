"""Tests for JSON-config-file loading of Settings."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic_settings import SettingsConfigDict

from linkedin_service.config import Settings


def _settings_class_for(json_file: Path) -> type[Settings]:
    """Build a Settings subclass whose config file is ``json_file``."""

    class _Settings(Settings):
        model_config = SettingsConfigDict(
            env_prefix="LINKEDIN_",
            env_file=".env",
            extra="ignore",
            json_file=str(json_file),
            json_file_encoding="utf-8",
        )

    return _Settings


def test_config_file_is_source_of_truth(tmp_path, monkeypatch) -> None:
    """Values in the injected JSON config file are loaded into Settings."""
    monkeypatch.delenv("LINKEDIN_PORT", raising=False)
    monkeypatch.delenv("LINKEDIN_LINKEDIN_CLIENT_ID", raising=False)
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "linkedin_client_id": "from-config",
                "linkedin_client_secret": "secret-from-config",
                "port": 9001,
            }
        ),
        encoding="utf-8",
    )

    settings = _settings_class_for(cfg)()

    assert settings.linkedin_client_id == "from-config"
    assert settings.linkedin_client_secret == "secret-from-config"
    assert settings.port == 9001
    assert settings.auth_configured is True


def test_env_overrides_config_file(tmp_path, monkeypatch) -> None:
    """Environment variables override values from the JSON config file."""
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"port": 9001}), encoding="utf-8")
    monkeypatch.setenv("LINKEDIN_PORT", "9999")

    settings = _settings_class_for(cfg)()

    assert settings.port == 9999


def test_missing_config_file_uses_defaults(tmp_path, monkeypatch) -> None:
    """A missing config file is not an error; field defaults apply."""
    monkeypatch.delenv("LINKEDIN_PORT", raising=False)
    settings = _settings_class_for(tmp_path / "does-not-exist.json")()

    assert settings.port == 8000
    assert settings.linkedin_scopes == "openid profile email w_member_social"
