"""Tests for config-file loading of Settings via robotsix-config."""

from __future__ import annotations

import json

from robotsix_config import load_config

from linkedin_service.config import Settings


def test_config_file_is_source_of_truth(tmp_path) -> None:
    """Values in the injected JSON config file are loaded into Settings."""
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

    settings = load_config(Settings, cfg)

    assert settings.linkedin_client_id.get_secret_value() == "from-config"
    assert settings.linkedin_client_secret.get_secret_value() == "secret-from-config"
    assert settings.port == 9001
    assert settings.auth_configured is True


def test_missing_config_file_uses_defaults(tmp_path) -> None:
    """A missing config file is not an error; field defaults apply."""
    settings = load_config(Settings, tmp_path / "does-not-exist.json")

    assert settings.port == 8000
    assert settings.linkedin_scopes == "openid profile email w_member_social"
