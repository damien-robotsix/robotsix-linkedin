"""Tests for the Settings panel endpoints (GET/PUT /config, versions, rollback)."""

from __future__ import annotations

import pytest

from linkedin_service.config import settings


@pytest.fixture(autouse=True)
def _restore_settings():
    """Snapshot and restore settings after each test to prevent leakage."""
    snapshot = settings.model_dump()
    yield
    for key, value in snapshot.items():
        setattr(settings, key, value)


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Point the config file at a throwaway path for each test.

    ``robotsix_config`` resolves ``ROBOTSIX_CONFIG_FILE`` at call time, so the
    Settings panel handlers write and read versions from this temp file rather
    than the repo's real ``config/config.json``. Each test gets a fresh path,
    so version history never leaks across tests.
    """
    monkeypatch.setenv("ROBOTSIX_CONFIG_FILE", str(tmp_path / "config.json"))
    yield


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
    resp = await client.put(
        "/config",
        json={
            "linkedin_client_id": "new-id",
            "linkedin_client_secret": "new-secret",
            "port": 9999,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] >= 1

    # Verify the live settings object was updated.
    assert settings.linkedin_client_id.get_secret_value() == "new-id"
    assert settings.linkedin_client_secret.get_secret_value() == "new-secret"
    assert settings.port == 9999


@pytest.mark.asyncio
async def test_put_config_partial_update(client):
    """PUT /config with only some fields leaves others unchanged."""
    original_port = settings.port
    resp = await client.put(
        "/config",
        json={"linkedin_client_id": "partial-id"},
    )
    assert resp.status_code == 200
    assert settings.linkedin_client_id.get_secret_value() == "partial-id"
    assert settings.port == original_port


@pytest.mark.asyncio
async def test_put_config_masked_secret_is_preserved(client):
    """Echoing the masked sentinel must not overwrite a stored secret."""
    # Establish a real secret first.
    resp = await client.put("/config", json={"linkedin_client_secret": "real-secret"})
    assert resp.status_code == 200

    # Echo the masked sentinel back alongside a different field.
    resp = await client.put(
        "/config",
        json={"linkedin_client_secret": "**********", "port": 9000},
    )
    assert resp.status_code == 200
    # The real secret is preserved, not replaced by the sentinel.
    assert settings.linkedin_client_secret.get_secret_value() == "real-secret"
    assert settings.port == 9000


@pytest.mark.asyncio
async def test_put_config_empty_secret_is_preserved(client):
    """An empty secret submission leaves the stored secret unchanged."""
    resp = await client.put("/config", json={"linkedin_client_secret": "real-secret"})
    assert resp.status_code == 200

    resp = await client.put("/config", json={"linkedin_client_secret": ""})
    assert resp.status_code == 200
    assert settings.linkedin_client_secret.get_secret_value() == "real-secret"


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


@pytest.mark.asyncio
async def test_get_config_versions_newest_first(client):
    """GET /config/versions lists recorded versions, newest first."""
    await client.put("/config", json={"port": 9000})
    await client.put("/config", json={"port": 9001})

    resp = await client.get("/config/versions")
    assert resp.status_code == 200
    versions = resp.json()["versions"]
    nums = [v["version"] for v in versions]
    assert nums == sorted(nums, reverse=True)
    assert nums[0] > nums[-1]


@pytest.mark.asyncio
async def test_rollback_restores_earlier_version(client):
    """POST /config/rollback restores an earlier version as a new one."""
    await client.put("/config", json={"port": 9000})  # version 1
    await client.put("/config", json={"port": 9001})  # version 2

    resp = await client.post("/config/rollback", json={"version": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # Append-only history: rolling back writes a new version, not a delete.
    assert body["version"] == 3
    assert settings.port == 9000


@pytest.mark.asyncio
async def test_rollback_missing_version_returns_400(client):
    """Rolling back to a version that does not exist returns 400."""
    resp = await client.post("/config/rollback", json={"version": 99})
    assert resp.status_code == 400
