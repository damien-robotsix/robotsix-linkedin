"""Tests for the Settings panel endpoints (GET/PUT /config)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from linkedin_service.config import settings


@pytest.fixture(autouse=True)
def _restore_settings():
    """Snapshot and restore settings after each test to prevent leakage."""
    snapshot = settings.model_dump()
    yield
    for key, value in snapshot.items():
        setattr(settings, key, value)


@pytest.mark.asyncio
async def test_get_config_masks_secrets(client):
    """GET /config returns config with secret fields masked."""
    resp = await client.get("/config")
    assert resp.status_code == 200
    body = resp.json()
    # SecretStr fields are masked by default in model_dump().
    assert "linkedin_client_id" in body
    assert "linkedin_client_secret" in body
    # The masked value should not contain the raw secret.
    assert body["linkedin_client_id"] != "real-secret"
    assert body["linkedin_client_secret"] != "real-secret"


@pytest.mark.asyncio
async def test_put_config_updates_fields(client):
    """PUT /config updates settings and persists."""
    with patch("linkedin_service.app.dump_config"):
        resp = await client.put(
            "/config",
            json={
                "linkedin_client_id": "new-id",
                "linkedin_client_secret": "new-secret",
                "port": 9999,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify the live settings object was updated.
    assert settings.linkedin_client_id.get_secret_value() == "new-id"
    assert settings.linkedin_client_secret.get_secret_value() == "new-secret"
    assert settings.port == 9999


@pytest.mark.asyncio
async def test_put_config_partial_update(client):
    """PUT /config with only some fields leaves others unchanged."""
    original_port = settings.port
    with patch("linkedin_service.app.dump_config"):
        resp = await client.put(
            "/config",
            json={"linkedin_client_id": "partial-id"},
        )
    assert resp.status_code == 200
    assert settings.linkedin_client_id.get_secret_value() == "partial-id"
    assert settings.port == original_port


@pytest.mark.asyncio
async def test_get_config_schema(client):
    """GET /config/schema returns a valid JSON Schema."""
    resp = await client.get("/config/schema")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["type"] == "object"
    assert "properties" in schema
    # Secret fields should be marked writeOnly.
    assert schema["properties"]["linkedin_client_id"]["writeOnly"] is True
    assert schema["properties"]["linkedin_client_secret"]["writeOnly"] is True
