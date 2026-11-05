"""Callback-level tests for OAuth ``state`` hardening on both auth flows.

Exercises ``/auth/callback`` (personal app) and ``/auth/org/callback``
(org app) through the shared parameterized implementation to confirm that
empty state is rejected, a valid state is single-use, and a mismatched
state is rejected without burning the stored nonce.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from linkedin_service import auth
from linkedin_service.config import settings


class _FakeResponse:
    status_code = 200
    is_error = False
    content = b"x"
    text = ""
    headers = httpx.Headers({})

    def json(self) -> dict[str, Any]:
        return {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def request(self, method: str, url: str, **_kwargs: Any) -> _FakeResponse:
        self.calls.append((method.lower(), url))
        return _FakeResponse()


@dataclass(frozen=True)
class _Flow:
    name: str
    callback: str
    store: Callable[[], auth.TokenStore]
    client_id_field: str
    client_secret_field: str


_FLOWS = [
    _Flow(
        "personal",
        "/auth/callback",
        lambda: auth.tokens,
        "linkedin_client_id",
        "linkedin_client_secret",
    ),
    _Flow(
        "org",
        "/auth/org/callback",
        lambda: auth.org_tokens,
        "linkedin_org_client_id",
        "linkedin_org_client_secret",
    ),
]


@pytest.fixture(params=_FLOWS, ids=lambda f: f.name)
def flow(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> _Flow:
    f: _Flow = request.param
    monkeypatch.setattr(settings, f.client_id_field, SecretStr("cid"))
    monkeypatch.setattr(settings, f.client_secret_field, SecretStr("csecret"))
    return f


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    fake = _FakeClient()
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *a, **k: fake)
    return fake


@pytest.mark.asyncio
async def test_empty_state_without_login_is_rejected(
    client: httpx.AsyncClient, flow: _Flow, fake_http: _FakeClient
) -> None:
    """``state=`` before any login must not match the empty stored state."""
    assert flow.store().state == ""
    resp = await client.get(flow.callback, params={"code": "attacker", "state": ""})
    assert resp.status_code == 400
    assert "state mismatch" in resp.text
    assert fake_http.calls == []
    assert flow.store().access_token == ""


@pytest.mark.asyncio
async def test_valid_state_is_single_use(
    client: httpx.AsyncClient, flow: _Flow, fake_http: _FakeClient
) -> None:
    """A valid state is consumed on first use; a replay is rejected."""
    flow.store().state = "nonce-1"
    first = await client.get(flow.callback, params={"code": "c1", "state": "nonce-1"})
    assert first.status_code == 200
    assert flow.store().state == ""
    assert flow.store().access_token == "tok"
    assert len(fake_http.calls) == 1

    replay = await client.get(flow.callback, params={"code": "c2", "state": "nonce-1"})
    assert replay.status_code == 400
    assert "state mismatch" in replay.text
    assert len(fake_http.calls) == 1


@pytest.mark.asyncio
async def test_mismatched_state_does_not_consume_stored_state(
    client: httpx.AsyncClient, flow: _Flow, fake_http: _FakeClient
) -> None:
    """A wrong state is rejected and the pending nonce stays usable."""
    flow.store().state = "nonce-2"
    bad = await client.get(flow.callback, params={"code": "c", "state": "tampered"})
    assert bad.status_code == 400
    assert "state mismatch" in bad.text
    assert flow.store().state == "nonce-2"
    assert fake_http.calls == []

    good = await client.get(flow.callback, params={"code": "c", "state": "nonce-2"})
    assert good.status_code == 200
    assert flow.store().state == ""


@pytest.mark.asyncio
async def test_login_state_round_trips_through_callback(
    client: httpx.AsyncClient, flow: _Flow, fake_http: _FakeClient
) -> None:
    """The state minted by the authorize URL is accepted exactly once."""
    build = auth.build_authorize_url if flow.name == "personal" else auth.build_org_authorize_url
    build()
    state = flow.store().state
    assert state
    ok = await client.get(flow.callback, params={"code": "c", "state": state})
    assert ok.status_code == 200
    replay = await client.get(flow.callback, params={"code": "c", "state": state})
    assert replay.status_code == 400
