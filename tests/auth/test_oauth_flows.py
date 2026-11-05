"""End-to-end regression tests for the personal and org OAuth flows.

The personal (``/auth/login`` → ``/auth/callback``) and org
(``/auth/org/login`` → ``/auth/org/callback``) flows share one
parameterized implementation (``auth.OAuthApp`` + ``_exchange_app_code`` and
``app._handle_oauth_callback``). These tests drive each flow over HTTP —
login, callback, token exchange and token storage — and pin the behaviour of
the original separate flows: the right credentials and redirect URI are sent,
tokens land only in the flow's own store/file, and the failure paths
(mismatched / empty / replayed state, missing code, provider errors) are
rejected identically for both.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from linkedin_service import auth
from linkedin_service.config import settings


class _FakeResponse:
    """Minimal stand-in for :class:`httpx.Response`."""

    def __init__(self, *, json_data: dict[str, Any] | None = None, status_code: int = 200) -> None:
        self._json = json_data if json_data is not None else {}
        self.status_code = status_code
        self.headers = httpx.Headers({})
        self.text = json.dumps(self._json)
        self.content = self.text.encode()

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self) -> dict[str, Any]:
        return self._json

    def raise_for_status(self) -> None:
        if self.is_error:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", auth.ACCESS_TOKEN_URL),
                response=self,  # type: ignore[arg-type]
            )


class _FakeLinkedIn:
    """Async context-manager stand-in for the outbound ``httpx.AsyncClient``."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __aenter__(self) -> _FakeLinkedIn:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((method.upper(), url, kwargs))
        return self._response


@dataclass(frozen=True)
class _Flow:
    """Everything that differs between the personal and org flows."""

    name: str
    login_path: str
    callback_path: str
    client_id: str
    client_secret: str
    success_message: str
    failure_prefix: str

    def store(self) -> auth.TokenStore:
        return auth.tokens if self.name == "personal" else auth.org_tokens

    def other_store(self) -> auth.TokenStore:
        return auth.org_tokens if self.name == "personal" else auth.tokens

    def token_file(self) -> Path:
        if self.name == "personal":
            return Path(settings.linkedin_token_file)
        return Path(settings.linkedin_org_token_file)

    def other_token_file(self) -> Path:
        if self.name == "personal":
            return Path(settings.linkedin_org_token_file)
        return Path(settings.linkedin_token_file)

    def redirect_uri(self) -> str:
        if self.name == "personal":
            return settings.linkedin_redirect_uri
        return settings.linkedin_org_redirect_uri


PERSONAL = _Flow(
    name="personal",
    login_path="/auth/login",
    callback_path="/auth/callback",
    client_id="personal-cid",
    client_secret="personal-secret",
    success_message="Authentication successful.",
    failure_prefix="Token exchange failed",
)
ORG = _Flow(
    name="org",
    login_path="/auth/org/login",
    callback_path="/auth/org/callback",
    client_id="org-cid",
    client_secret="org-secret",
    success_message="Organization app authentication successful.",
    failure_prefix="Org token exchange failed",
)

FLOWS = pytest.mark.parametrize("flow", [PERSONAL, ORG], ids=lambda f: f.name)

_TOKEN_RESPONSE = {
    "access_token": "acc-xyz",
    "refresh_token": "ref-xyz",
    "expires_in": 3600,
    "token_type": "Bearer",
    "scope": "some scope",
}


@pytest.fixture(autouse=True)
def _configure_both_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure both LinkedIn apps so either login route can be exercised."""
    monkeypatch.setattr(settings, "linkedin_client_id", SecretStr(PERSONAL.client_id))
    monkeypatch.setattr(settings, "linkedin_client_secret", SecretStr(PERSONAL.client_secret))
    monkeypatch.setattr(settings, "linkedin_org_client_id", SecretStr(ORG.client_id))
    monkeypatch.setattr(settings, "linkedin_org_client_secret", SecretStr(ORG.client_secret))


def _patch_linkedin(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> _FakeLinkedIn:
    """Route the outbound token request to a fake.

    Must be called after the ASGI ``client`` fixture is built, since it
    replaces ``httpx.AsyncClient`` module-wide.
    """
    fake = _FakeLinkedIn(response)
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda *a, **k: fake)
    return fake


async def _login(client: httpx.AsyncClient, flow: _Flow) -> str:
    """Hit the flow's login route and return the ``state`` it issued."""
    resp = await client.get(flow.login_path, follow_redirects=False)
    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    assert location.startswith(auth.AUTHORIZE_URL)
    params = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    assert params["client_id"] == [flow.client_id]
    assert params["redirect_uri"] == [flow.redirect_uri()]
    assert params["response_type"] == ["code"]
    (state,) = params["state"]
    assert state and flow.store().state == state
    # Login on one flow never touches the other flow's pending state.
    assert flow.other_store().state == ""
    return state


def _assert_untouched(store: auth.TokenStore) -> None:
    assert store.access_token == ""
    assert store.refresh_token == ""
    assert store.expires_at == 0.0


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@FLOWS
@pytest.mark.asyncio
async def test_full_flow_exchanges_code_and_stores_tokens(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, flow: _Flow
) -> None:
    state = await _login(client, flow)
    fake = _patch_linkedin(monkeypatch, _FakeResponse(json_data=_TOKEN_RESPONSE))

    resp = await client.get(flow.callback_path, params={"code": "the-code", "state": state})

    assert resp.status_code == 200
    assert resp.json() == {
        "message": flow.success_message,
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": "some scope",
    }
    # Exactly one token request, with this flow's credentials and redirect URI.
    assert len(fake.calls) == 1
    method, url, kwargs = fake.calls[0]
    assert (method, url) == ("POST", auth.ACCESS_TOKEN_URL)
    assert kwargs["data"] == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "redirect_uri": flow.redirect_uri(),
        "client_id": flow.client_id,
        "client_secret": flow.client_secret,
    }
    # Tokens are stored in this flow's store and persisted to its own file.
    store = flow.store()
    assert store.access_token == "acc-xyz"
    assert store.refresh_token == "ref-xyz"
    assert store.expires_at > 3600
    assert store.state == ""
    persisted = json.loads(flow.token_file().read_text())
    assert persisted["access_token"] == "acc-xyz"
    assert persisted["refresh_token"] == "ref-xyz"
    assert "state" not in persisted
    # The other flow's store and token file are never written.
    _assert_untouched(flow.other_store())
    assert not flow.other_token_file().exists()


@FLOWS
@pytest.mark.asyncio
async def test_exchange_function_matches_callback_behaviour(
    monkeypatch: pytest.MonkeyPatch, flow: _Flow
) -> None:
    """The public ``exchange_code`` / ``exchange_org_code`` wrappers target the right app."""
    exchange = auth.exchange_code if flow.name == "personal" else auth.exchange_org_code
    flow.store().state = "direct-state"
    fake = _patch_linkedin(monkeypatch, _FakeResponse(json_data={"access_token": "only-access"}))

    data = await exchange("c", "direct-state")

    assert data == {"access_token": "only-access"}
    assert fake.calls[0][2]["data"]["client_id"] == flow.client_id
    assert flow.store().access_token == "only-access"
    # No refresh token / expiry in the response: defaults match the original flows.
    assert flow.store().refresh_token == ""
    _assert_untouched(flow.other_store())


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@FLOWS
@pytest.mark.asyncio
async def test_callback_with_mismatched_state_is_rejected(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, flow: _Flow
) -> None:
    state = await _login(client, flow)
    fake = _patch_linkedin(monkeypatch, _FakeResponse(json_data=_TOKEN_RESPONSE))

    resp = await client.get(flow.callback_path, params={"code": "c", "state": "tampered"})

    assert resp.status_code == 400
    assert "state mismatch" in resp.json()["error"]["detail"]
    assert fake.calls == []
    _assert_untouched(flow.store())
    # A failed check does not burn the pending nonce.
    assert flow.store().state == state


@FLOWS
@pytest.mark.asyncio
async def test_callback_with_other_flows_state_is_rejected(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, flow: _Flow
) -> None:
    """A state issued by one flow's login cannot complete the other flow."""
    other = ORG if flow is PERSONAL else PERSONAL
    other_state = await _login(client, other)
    fake = _patch_linkedin(monkeypatch, _FakeResponse(json_data=_TOKEN_RESPONSE))

    resp = await client.get(flow.callback_path, params={"code": "c", "state": other_state})

    assert resp.status_code == 400
    assert fake.calls == []
    _assert_untouched(auth.tokens)
    _assert_untouched(auth.org_tokens)


@FLOWS
@pytest.mark.asyncio
async def test_callback_with_empty_state_before_login_is_rejected(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, flow: _Flow
) -> None:
    fake = _patch_linkedin(monkeypatch, _FakeResponse(json_data=_TOKEN_RESPONSE))

    resp = await client.get(flow.callback_path, params={"code": "attacker", "state": ""})

    assert resp.status_code == 400
    assert "state mismatch" in resp.json()["error"]["detail"]
    assert fake.calls == []
    _assert_untouched(flow.store())


@FLOWS
@pytest.mark.asyncio
async def test_callback_state_is_single_use(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, flow: _Flow
) -> None:
    state = await _login(client, flow)
    fake = _patch_linkedin(monkeypatch, _FakeResponse(json_data=_TOKEN_RESPONSE))

    first = await client.get(flow.callback_path, params={"code": "c1", "state": state})
    replay = await client.get(flow.callback_path, params={"code": "c2", "state": state})

    assert first.status_code == 200
    assert replay.status_code == 400
    assert "state mismatch" in replay.json()["error"]["detail"]
    assert len(fake.calls) == 1


@FLOWS
@pytest.mark.parametrize(
    "params",
    [{"state": "s"}, {"code": "c"}, {}],
    ids=["missing-code", "missing-state", "missing-both"],
)
@pytest.mark.asyncio
async def test_callback_missing_params_returns_422(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    flow: _Flow,
    params: dict[str, str],
) -> None:
    await _login(client, flow)
    fake = _patch_linkedin(monkeypatch, _FakeResponse(json_data=_TOKEN_RESPONSE))

    resp = await client.get(flow.callback_path, params=params)

    assert resp.status_code == 422
    assert fake.calls == []
    _assert_untouched(flow.store())


@FLOWS
@pytest.mark.asyncio
async def test_callback_surfaces_provider_error_as_502(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, flow: _Flow
) -> None:
    state = await _login(client, flow)
    fake = _patch_linkedin(
        monkeypatch,
        _FakeResponse(
            json_data={"error": "invalid_grant", "error_description": "bad code"},
            status_code=400,
        ),
    )

    resp = await client.get(flow.callback_path, params={"code": "bad", "state": state})

    assert resp.status_code == 502
    detail = resp.json()["error"]["detail"]
    assert detail.startswith(flow.failure_prefix)
    assert "invalid_grant" in detail
    assert len(fake.calls) == 1
    _assert_untouched(flow.store())
    assert not flow.token_file().exists()
    _assert_untouched(flow.other_store())


@FLOWS
@pytest.mark.asyncio
async def test_login_without_credentials_returns_503(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, flow: _Flow
) -> None:
    if flow.name == "personal":
        monkeypatch.setattr(settings, "linkedin_client_id", SecretStr(""))
    else:
        monkeypatch.setattr(settings, "linkedin_org_client_id", SecretStr(""))

    resp = await client.get(flow.login_path, follow_redirects=False)

    assert resp.status_code == 503
    assert flow.store().state == ""
